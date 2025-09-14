// SPDX-License-Identifier: GPL-2.0
/* Refactored AF_XDP forwarder: UMEM owns FQ/CQ, ports share them. */

#define _GNU_SOURCE
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>
#include <getopt.h>
#include <netinet/ether.h>
#include <net/if.h>
#include <errno.h>

#include <linux/err.h>
#include <linux/if_link.h>
#include <linux/if_xdp.h>

#include <xdp/libxdp.h>
#include <xdp/xsk.h>

#define ARRAY_SIZE(x) (sizeof(x) / sizeof((x)[0]))
#define MAX_INTERFACES 8
#define MAX_THREADS 8

typedef __u64 u64;
typedef __u32 u32;
typedef __u16 u16;
typedef __u8  u8;

/* ------------------------------
 * UMEM manager (owns FQ/CQ + global freelist)
 * ------------------------------ */

struct umem_mgr_params {
	u32 n_frames;          /* total frames in UMEM */
	u32 frame_size;        /* XSK_UMEM__DEFAULT_FRAME_SIZE etc */
	int mmap_flags;        /* MAP_HUGETLB optional */
};

struct umem_mgr {
	void *addr;                   /* mmap base */
	struct xsk_umem *umem;        /* libxdp umem */
	struct xsk_ring_prod fq;      /* ✅ UMEM owns Fill Queue */
	struct xsk_ring_cons cq;      /* ✅ UMEM owns Completion Queue */
	struct xsk_umem_config umem_cfg;

	/* Global freelist: stack of frame addresses. */
	u64 *free_addrs;
	u32 free_top;                 /* next push index (also count of free frames) */
	u32 n_frames;
	u32 frame_size;

	pthread_mutex_t lock;
	int fq_initialized;           /* Track if FQ has been pre-filled */
};

static struct umem_mgr *
umem_mgr_create(const struct umem_mgr_params *pp,
                const struct xsk_umem_config *umem_cfg)
{
	struct umem_mgr *u = NULL;
	struct rlimit r = { RLIM_INFINITY, RLIM_INFINITY };
	size_t total_sz = (size_t)pp->n_frames * pp->frame_size;

	if (setrlimit(RLIMIT_MEMLOCK, &r)) {
		perror("setrlimit RLIMIT_MEMLOCK");
		return NULL;
	}

	u = calloc(1, sizeof(*u));
	if (!u) return NULL;

	u->n_frames  = pp->n_frames;
	u->frame_size = pp->frame_size;
	memcpy(&u->umem_cfg, umem_cfg, sizeof(*umem_cfg));

	/* mmap backing memory */
	u->addr = mmap(NULL, total_sz,
	               PROT_READ | PROT_WRITE,
	               MAP_PRIVATE | MAP_ANONYMOUS | pp->mmap_flags,
	               -1, 0);
	if (u->addr == MAP_FAILED) {
		perror("mmap UMEM");
		free(u);
		return NULL;
	}

	/* Create UMEM with FQ/CQ owned by UMEM */
	int status = xsk_umem__create(&u->umem, u->addr, total_sz,
	                              &u->fq, &u->cq, &u->umem_cfg);
	if (status) {
		fprintf(stderr, "xsk_umem__create failed: %d\n", status);
		munmap(u->addr, total_sz);
		free(u);
		return NULL;
	}

	/* Global freelist */
	u->free_addrs = malloc(sizeof(u64) * u->n_frames);
	if (!u->free_addrs) {
		xsk_umem__delete(u->umem);
		munmap(u->addr, total_sz);
		free(u);
		return NULL;
	}
	for (u32 i = 0; i < u->n_frames; i++)
		u->free_addrs[i] = (u64)i * u->frame_size;
	u->free_top = u->n_frames;

	if (pthread_mutex_init(&u->lock, NULL)) {
		free(u->free_addrs);
		xsk_umem__delete(u->umem);
		munmap(u->addr, total_sz);
		free(u);
		return NULL;
	}

	return u;
}

static void
umem_mgr_destroy(struct umem_mgr *u)
{
	if (!u) return;
	size_t total_sz = (size_t)u->n_frames * u->frame_size;
	pthread_mutex_destroy(&u->lock);
	free(u->free_addrs);
	xsk_umem__delete(u->umem);
	munmap(u->addr, total_sz);
	free(u);
}

/* Bulk pop up to 'want' addresses from freelist into out[]. Returns count. */
static u32
umem_alloc(struct umem_mgr *u, u32 want, u64 out[])
{
	if (!want) return 0;
	pthread_mutex_lock(&u->lock);
	u32 avail = u->free_top;
	if (want > avail) want = avail;
	for (u32 i = 0; i < want; i++)
		out[i] = u->free_addrs[--u->free_top];
	pthread_mutex_unlock(&u->lock);
	return want;
}

/* Bulk push 'count' addresses back to freelist. */
static void
umem_free(struct umem_mgr *u, u32 count, const u64 addrs[])
{
	if (!count) return;
	pthread_mutex_lock(&u->lock);
	for (u32 i = 0; i < count; i++) {
		if (u->free_top < u->n_frames)
			u->free_addrs[u->free_top++] = addrs[i];
	}
	pthread_mutex_unlock(&u->lock);
}

static void
umem_free_one(struct umem_mgr *u, u64 addr)
{
	umem_free(u, 1, &addr);
}

/* ✅ NEW: UMEM manager handles FQ filling */
static int
umem_mgr_fill_fq(struct umem_mgr *u, u32 want)
{
	if (!want) return 0;
	
	u64 frames[want];
	u32 got = umem_alloc(u, want, frames);
	if (!got) return 0;
	
	u32 pos;
	int reserved = xsk_ring_prod__reserve(&u->fq, got, &pos);
	if (reserved != (int)got) {
		/* Put frames back to freelist */
		umem_free(u, got, frames);
		return reserved < 0 ? reserved : 0;
	}
	
	for (u32 i = 0; i < got; i++)
		*xsk_ring_prod__fill_addr(&u->fq, pos + i) = frames[i];
	xsk_ring_prod__submit(&u->fq, got);
	return got;
}

/* ✅ NEW: UMEM manager processes CQ completions */
static void
umem_mgr_process_cq(struct umem_mgr *u)
{
	u32 pos;
	u32 n = xsk_ring_cons__peek(&u->cq, 64, &pos);
	for (u32 i = 0; i < n; i++) {
		u64 addr = *xsk_ring_cons__comp_addr(&u->cq, pos + i);
		umem_free_one(u, addr);
	}
	if (n) xsk_ring_cons__release(&u->cq, n);
}

/* ✅ NEW: Initialize FQ with initial frames */
static int
umem_mgr_init_fq(struct umem_mgr *u)
{
	if (u->fq_initialized) return 0;
	
	u32 want = u->umem_cfg.fill_size;
	if (!want) want = 64;
	
	int filled = umem_mgr_fill_fq(u, want);
	if (filled <= 0) {
		fprintf(stderr, "Failed to initialize FQ with %u frames\n", want);
		return -1;
	}
	
	u->fq_initialized = 1;
	printf("Initialized FQ with %d frames\n", filled);
	return 0;
}

/* ------------------------------
 * Port (no longer owns FQ/CQ)
 * ------------------------------ */

struct port_params {
	struct umem_mgr *u;      /* shared UMEM manager */
	const char *iface;
	u32 iface_queue;
	struct xsk_socket_config xsk_cfg;
};

struct port {
	struct port_params params;
	
	struct xsk_ring_cons rxq;     /* ✅ Port-specific RX queue */
	struct xsk_ring_prod txq;     /* ✅ Port-specific TX queue */
	struct xsk_socket *xsk;
	/* ❌ Removed: umem_fq, umem_cq, umem_fq_initialized */
	
	u64 n_pkts_rx;
	u64 n_pkts_tx;
};

static void
port_free(struct port *p)
{
	if (!p) return;
	if (p->xsk)
		xsk_socket__delete(p->xsk);
	free(p);
}

static struct port *
port_init(struct port_params *params)
{
	struct port *p = calloc(1, sizeof(*p));
	if (!p) return NULL;

	memcpy(&p->params, params, sizeof(p->params));

	/* ✅ Create shared socket using UMEM's FQ/CQ */
	int status = xsk_socket__create_shared(&p->xsk,
	                                       params->iface,
	                                       params->iface_queue,
	                                       params->u->umem,
	                                       &p->rxq,
	                                       &p->txq,
	                                       &params->u->fq,     /* ✅ Use UMEM's FQ */
	                                       &params->u->cq,     /* ✅ Use UMEM's CQ */
	                                       &params->xsk_cfg);
	if (status) {
		fprintf(stderr, "xsk_socket__create_shared(%s,%u) failed: %d\n",
		        params->iface, params->iface_queue, status);
		port_free(p);
		return NULL;
	}

	return p;
}

/* ------------------------------
 * Forwarding logic (simplified)
 * ------------------------------ */

static int
forward_one_packet(struct port *rx, struct port *tx)
{
	struct umem_mgr *u = rx->params.u;  /* shared UMEM manager */
	
	/* ✅ Process CQ completions via UMEM manager */
	umem_mgr_process_cq(u);
	
	/* Peek exactly one packet from RX. */
	u32 rpos;
	u32 n = xsk_ring_cons__peek(&rx->rxq, 1, &rpos);
	if (!n) {
		/* ✅ Check UMEM's FQ for wakeup */
		if (xsk_ring_prod__needs_wakeup(&u->fq)) {
			struct pollfd pfd = { .fd = xsk_socket__fd(rx->xsk), .events = POLLIN };
			(void)poll(&pfd, 1, 0);
		}
		return 0;
	}

	const struct xdp_desc *rx_desc = xsk_ring_cons__rx_desc(&rx->rxq, rpos);
	u64 addr = rx_desc->addr;
	u32 len = rx_desc->len;

	/* Reserve slot in TX queue. */
	u32 tpos;
	while (xsk_ring_prod__reserve(&tx->txq, 1, &tpos) != 1) {
		if (xsk_ring_prod__needs_wakeup(&tx->txq)) {
			struct pollfd pfd = { .fd = xsk_socket__fd(tx->xsk), .events = POLLOUT };
			(void)poll(&pfd, 1, 0);
		}
	}

	/* Copy packet data if needed (or just forward the frame) */
	struct xdp_desc *tx_desc = xsk_ring_prod__tx_desc(&tx->txq, tpos);
	tx_desc->addr = addr;
	tx_desc->len = len;

	/* Submit TX and release RX. */
	xsk_ring_prod__submit(&tx->txq, 1);
	xsk_ring_cons__release(&rx->rxq, 1);

	/* Kick TX if needed. */
	if (xsk_ring_prod__needs_wakeup(&tx->txq)) {
		struct pollfd pfd = { .fd = xsk_socket__fd(tx->xsk), .events = POLLOUT };
		(void)poll(&pfd, 1, 0);
	}

	/* Replenish FQ if needed */
	u32 fq_free = xsk_prod_nb_free(&u->fq, u->umem_cfg.fill_size);
	if (fq_free > u->umem_cfg.fill_size / 2) {
		umem_mgr_fill_fq(u, fq_free);
	}

	rx->n_pkts_rx++;
	tx->n_pkts_tx++;
	return 1;
}

/* ------------------------------
 * Thread management
 * ------------------------------ */

struct thread_data {
	int thread_id;
	struct port **ports;
	u32 n_ports;
	struct umem_mgr *umem;
	volatile int *stop_flag;
};

static void *
thread_func(void *arg)
{
	struct thread_data *t = (struct thread_data *)arg;
	
	printf("Thread %d: managing %u ports\n", t->thread_id, t->n_ports);
	
	while (!*t->stop_flag) {
		int forwarded = 0;
		
		/* Simple round-robin forwarding between ports */
		for (u32 i = 0; i < t->n_ports; i++) {
			for (u32 j = 0; j < t->n_ports; j++) {
				if (i != j) {
					forwarded += forward_one_packet(t->ports[i], t->ports[j]);
				}
			}
		}
		
		if (!forwarded) {
			/* No packets forwarded, brief pause */
			usleep(1);
		}
	}
	
	return NULL;
}

/* ------------------------------
 * Main
 * ------------------------------ */

static volatile int stop_flag = 0;

static void
signal_handler(int sig)
{
	(void)sig;
	stop_flag = 1;
}

static void
print_stats(struct port **ports, u32 n_ports)
{
	printf("\n=== Port Statistics ===\n");
	for (u32 i = 0; i < n_ports; i++) {
		printf("Port %u: RX=%llu TX=%llu\n", i, 
		       (unsigned long long)ports[i]->n_pkts_rx, 
		       (unsigned long long)ports[i]->n_pkts_tx);
	}
	printf("========================\n");
}

int main(int argc, char **argv)
{
	/* Default parameters */
	const char *interfaces[] = {"veth0s8", "veth0s1"};
	u32 n_interfaces = 2;
	u32 n_threads = 1;
	u32 n_frames = 4096;
	u32 frame_size = XSK_UMEM__DEFAULT_FRAME_SIZE;
	
	/* Parse simple arguments (extend as needed) */
	if (argc > 1) {
		n_threads = atoi(argv[1]);
		if (n_threads == 0) n_threads = 1;
		if (n_threads > MAX_THREADS) n_threads = MAX_THREADS;
	}
	
	printf("AF_XDP Forwarder (Refactored)\n");
	printf("Interfaces: %u, Threads: %u, Frames: %u\n", 
	       n_interfaces, n_threads, n_frames);
	
	/* Create UMEM manager */
	struct umem_mgr_params umem_params = {
		.n_frames = n_frames,
		.frame_size = frame_size,
		.mmap_flags = 0
	};
	
	struct xsk_umem_config umem_cfg = {
		.fill_size = XSK_RING_PROD__DEFAULT_NUM_DESCS,
		.comp_size = XSK_RING_CONS__DEFAULT_NUM_DESCS,
		.frame_size = frame_size,
		.frame_headroom = XSK_UMEM__DEFAULT_FRAME_HEADROOM,
		.flags = 0
	};
	
	struct umem_mgr *umem = umem_mgr_create(&umem_params, &umem_cfg);
	if (!umem) {
		fprintf(stderr, "Failed to create UMEM manager\n");
		return 1;
	}
	
	/* Initialize FQ with frames */
	if (umem_mgr_init_fq(umem) < 0) {
		umem_mgr_destroy(umem);
		return 1;
	}
	
	/* ✅ Fixed: Declare arrays with fixed size to avoid VLA issues */
	struct port *ports[MAX_INTERFACES];
	pthread_t threads[MAX_THREADS];
	struct thread_data thread_data[MAX_THREADS];
	
	/* Create ports */
	for (u32 i = 0; i < n_interfaces; i++) {
		struct port_params port_params = {
			.u = umem,
			.iface = interfaces[i],
			.iface_queue = 0,
			.xsk_cfg = {
				.rx_size = XSK_RING_CONS__DEFAULT_NUM_DESCS,
				.tx_size = XSK_RING_PROD__DEFAULT_NUM_DESCS,
				.bind_flags = XDP_USE_NEED_WAKEUP,
			}
		};
		
		ports[i] = port_init(&port_params);
		if (!ports[i]) {
			fprintf(stderr, "Failed to create port %u (%s)\n", i, interfaces[i]);
			goto cleanup;
		}
		printf("Created port %u: %s\n", i, interfaces[i]);
	}
	
	/* Setup signal handling */
	signal(SIGINT, signal_handler);
	signal(SIGTERM, signal_handler);
	
	/* Create and start threads */
	u32 ports_per_thread = n_interfaces / n_threads;
	if (ports_per_thread == 0) ports_per_thread = 1;
	
	for (u32 i = 0; i < n_threads; i++) {
		thread_data[i].thread_id = i;
		thread_data[i].ports = &ports[i * ports_per_thread];
		thread_data[i].n_ports = (i == n_threads - 1) ? 
			n_interfaces - (i * ports_per_thread) : ports_per_thread;
		thread_data[i].umem = umem;
		thread_data[i].stop_flag = &stop_flag;
		
		if (pthread_create(&threads[i], NULL, thread_func, &thread_data[i])) {
			fprintf(stderr, "Failed to create thread %u\n", i);
			stop_flag = 1;
			break;
		}
	}
	
	/* Stats reporting */
	while (!stop_flag) {
		sleep(1);
		if (!stop_flag) print_stats(ports, n_interfaces);
	}
	
	/* Wait for threads to finish */
	for (u32 i = 0; i < n_threads; i++) {
		pthread_join(threads[i], NULL);
	}
	
	print_stats(ports, n_interfaces);
	
cleanup:
	/* Cleanup ports */
	for (u32 i = 0; i < n_interfaces; i++) {
		if (ports[i]) port_free(ports[i]);
	}
	
	/* Cleanup UMEM */
	umem_mgr_destroy(umem);
	
	printf("Shutdown complete\n");
	return 0;
}