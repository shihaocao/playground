// SPDX-License-Identifier: GPL-2.0
/* Simplified AF_XDP forwarder: single shared UMEM + global freelist. */

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

typedef __u64 u64;
typedef __u32 u32;
typedef __u16 u16;
typedef __u8  u8;

/* ------------------------------
 * UMEM manager (global freelist)
 * ------------------------------ */

struct umem_mgr_params {
	u32 n_frames;          /* total frames in UMEM */
	u32 frame_size;        /* XSK_UMEM__DEFAULT_FRAME_SIZE etc */
	int mmap_flags;        /* MAP_HUGETLB optional */
};

struct umem_mgr {
	void *addr;                   /* mmap base */
	struct xsk_umem *umem;        /* libxdp umem */
	struct xsk_ring_prod fq;      /* UMEM Fill ring (per socket via create_shared, but we keep cfg here) */
	struct xsk_ring_cons cq;      /* UMEM Comp ring (ditto) */
	struct xsk_umem_config umem_cfg;

	/* Global freelist: stack of frame addresses. */
	u64 *free_addrs;
	u32 free_top;                 /* next push index (also count of free frames) */
	u32 n_frames;
	u32 frame_size;

	pthread_mutex_t lock;
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

	/* Create UMEM */
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
static inline u32
umem_alloc(struct umem_mgr *u, u32 want, u64 *out)
{
	u32 got = 0;
	pthread_mutex_lock(&u->lock);
	got = (u->free_top >= want) ? want : u->free_top;
	for (u32 i = 0; i < got; i++)
		out[i] = u->free_addrs[--u->free_top];
	pthread_mutex_unlock(&u->lock);
	return got;
}

/* Push a single frame address back to freelist. */
static inline void
umem_free_one(struct umem_mgr *u, u64 addr)
{
	pthread_mutex_lock(&u->lock);
	u->free_addrs[u->free_top++] = addr;
	pthread_mutex_unlock(&u->lock);
}

/* ------------------------------
 * Port & forwarding
 * ------------------------------ */

struct port_params {
	struct xsk_socket_config xsk_cfg;
	struct umem_mgr *u;
	const char *iface;
	u32 iface_queue;
};

struct port {
	struct port_params params;

	struct xsk_ring_cons rxq;
	struct xsk_ring_prod txq;
	struct xsk_ring_prod umem_fq;
	struct xsk_ring_cons umem_cq;
	struct xsk_socket *xsk;
	int umem_fq_initialized;

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

	/* Create shared socket using global UMEM. */
	int status = xsk_socket__create_shared(&p->xsk,
	                                       params->iface,
	                                       params->iface_queue,
	                                       params->u->umem,
	                                       &p->rxq,
	                                       &p->txq,
	                                       &p->umem_fq,
	                                       &p->umem_cq,
	                                       &params->xsk_cfg);
	if (status) {
		fprintf(stderr, "xsk_socket__create_shared(%s,%u) failed: %d\n",
		        params->iface, params->iface_queue, status);
		port_free(p);
		return NULL;
	}

	/* Initial FQ fill */
	u32 need = params->u->umem_cfg.fill_size;
	if (need > 0) {
		u64 tmp[4096];
		if (need > ARRAY_SIZE(tmp)) need = ARRAY_SIZE(tmp);

		u32 got = umem_alloc(params->u, need, tmp);
		if (!got) {
			fprintf(stderr, "Initial UMEM FQ fill: no frames\n");
			port_free(p);
			return NULL;
		}

		u32 pos;
		int r = xsk_ring_prod__reserve(&p->umem_fq, got, &pos);
		if (r != (int)got) {
			fprintf(stderr, "FQ reserve %u got %d\n", got, r);
			port_free(p);
			return NULL;
		}
		for (u32 i = 0; i < got; i++)
			*xsk_ring_prod__fill_addr(&p->umem_fq, pos + i) = tmp[i];
		xsk_ring_prod__submit(&p->umem_fq, got);
		p->umem_fq_initialized = 1;
	}

	return p;
}

static inline void
swap_mac_addresses(void *data)
{
	struct ether_header *eth = (struct ether_header *)data;
	struct ether_addr *src_addr = (struct ether_addr *)&eth->ether_shost;
	struct ether_addr *dst_addr = (struct ether_addr *)&eth->ether_dhost;
	struct ether_addr tmp = *src_addr;
	*src_addr = *dst_addr;
	*dst_addr = tmp;
}

/* ------------------------------
 * Threading & process scaffolding
 * ------------------------------ */

#ifndef MAX_PORTS_PER_THREAD
#define MAX_PORTS_PER_THREAD 16
#endif

struct thread_data {
	struct port *ports_rx[MAX_PORTS_PER_THREAD];
	struct port *ports_tx[MAX_PORTS_PER_THREAD];
	u32 n_ports_rx;
	struct burst_rx burst_rx;
	struct burst_tx burst_tx[MAX_PORTS_PER_THREAD];
	u32 cpu_core_id;
	int quit;
};

/* Try to recycle TX completions, RX 1 packet, swap MACs, TX it, and
 * replenish FQ with 1 fresh frame. Returns 1 if a packet was forwarded,
 * 0 if nothing was available on RX.
 */
static inline int
port_pump_once(struct port *rx, struct port *tx)
{
    /* 1) Recycle completions on TX side so the freelist doesn’t starve. */
    {
        u32 want = tx->params.u->umem_cfg.comp_size;
        if (!want) want = 64;
        u32 cpos;
        u32 n_cq = xsk_ring_cons__peek(&tx->umem_cq, want, &cpos);
        for (u32 i = 0; i < n_cq; i++) {
            u64 addr = *xsk_ring_cons__comp_addr(&tx->umem_cq, cpos + i);
            umem_free_one(tx->params.u, addr);
        }
        if (n_cq) xsk_ring_cons__release(&tx->umem_cq, n_cq);
    }

    /* 2) Peek exactly one packet from RX. */
    u32 rpos;
    u32 n = xsk_ring_cons__peek(&rx->rxq, 1, &rpos);
    if (!n) {
        if (xsk_ring_prod__needs_wakeup(&rx->umem_fq)) {
            struct pollfd pfd = { .fd = xsk_socket__fd(rx->xsk), .events = POLLIN };
            (void)poll(&pfd, 1, 0);
        }
        return 0; /* nothing to do */
    }

    const struct xdp_desc *d = xsk_ring_cons__rx_desc(&rx->rxq, rpos);
    u64 addr = d->addr;
    u32 len  = d->len;

    /* Consume RX descriptor. */
    xsk_ring_cons__release(&rx->rxq, 1);
    rx->n_pkts_rx++;

    /* 3) Edit packet in-place if desired (e.g., swap MACs). */
    {
        u64 data_addr = xsk_umem__add_offset_to_addr(addr);
        u8 *pkt = xsk_umem__get_data(rx->params.u->addr, data_addr);
        swap_mac_addresses(pkt);
    }

    /* 4) Transmit immediately on TX. */
    u32 tpos;
    while (xsk_ring_prod__reserve(&tx->txq, 1, &tpos) != 1) {
        if (xsk_ring_prod__needs_wakeup(&tx->txq))
            sendto(xsk_socket__fd(tx->xsk), NULL, 0, MSG_DONTWAIT, NULL, 0);
        /* Optionally add a small bounded retry or yield here */
    }

    struct xdp_desc *td = xsk_ring_prod__tx_desc(&tx->txq, tpos);
    td->addr = addr;
    td->len  = len;
    xsk_ring_prod__submit(&tx->txq, 1);
    if (xsk_ring_prod__needs_wakeup(&tx->txq))
        sendto(xsk_socket__fd(tx->xsk), NULL, 0, MSG_DONTWAIT, NULL, 0);
    tx->n_pkts_tx++;

    /* 5) Replenish RX UMEM FQ with one fresh frame from freelist. */
    {
        u64 fresh;
        while (umem_alloc(rx->params.u, 1, &fresh) != 1) {
            /* Wait for completions to refill freelist */
            if (xsk_ring_prod__needs_wakeup(&rx->umem_fq)) {
                struct pollfd pfd = { .fd = xsk_socket__fd(rx->xsk), .events = POLLIN };
                (void)poll(&pfd, 1, 0);
            }
            /* Also recycle from TX CQ again to free frames faster */
            u32 cpos2, got2 = xsk_ring_cons__peek(&tx->umem_cq, 64, &cpos2);
            for (u32 i = 0; i < got2; i++) {
                u64 a2 = *xsk_ring_cons__comp_addr(&tx->umem_cq, cpos2 + i);
                umem_free_one(tx->params.u, a2);
            }
            if (got2) xsk_ring_cons__release(&tx->umem_cq, got2);
        }

        u32 fpos;
        while (xsk_ring_prod__reserve(&rx->umem_fq, 1, &fpos) != 1) {
            if (xsk_ring_prod__needs_wakeup(&rx->umem_fq)) {
                struct pollfd pfd = { .fd = xsk_socket__fd(rx->xsk), .events = POLLIN };
                (void)poll(&pfd, 1, 0);
            }
        }
        *xsk_ring_prod__fill_addr(&rx->umem_fq, fpos) = fresh;
        xsk_ring_prod__submit(&rx->umem_fq, 1);
    }

    return 1;
}

static void *
thread_func(void *arg)
{
    struct thread_data *t = arg;
    cpu_set_t cpu_cores;

    CPU_ZERO(&cpu_cores);
    CPU_SET(t->cpu_core_id, &cpu_cores);
    pthread_setaffinity_np(pthread_self(), sizeof(cpu_set_t), &cpu_cores);

    /* Simple round-robin over this thread’s RX/TX pairs. */
    for (u32 i = 0; !t->quit; i = (i + 1) & (t->n_ports_rx - 1)) {
        (void)port_pump_once(t->ports_rx[i], t->ports_tx[i]);
        /* no busy sleep; if there’s nothing, port_pump_once() returns fast */
    }
    return NULL;
}

/* ------------------------------
 * CLI / stats / main
 * ------------------------------ */

static const struct umem_mgr_params umem_params_default = {
	.n_frames   = 64 * 1024,
	.frame_size = XSK_UMEM__DEFAULT_FRAME_SIZE,
	.mmap_flags = 0,
};

static const struct xsk_umem_config umem_cfg_default = {
	.fill_size     = XSK_RING_PROD__DEFAULT_NUM_DESCS * 2,
	.comp_size     = XSK_RING_CONS__DEFAULT_NUM_DESCS,
	.frame_size    = XSK_UMEM__DEFAULT_FRAME_SIZE,
	.frame_headroom= XSK_UMEM__DEFAULT_FRAME_HEADROOM,
	.flags         = 0,
};

static const struct port_params port_params_default = {
	.xsk_cfg = {
		.rx_size     = XSK_RING_CONS__DEFAULT_NUM_DESCS,
		.tx_size     = XSK_RING_PROD__DEFAULT_NUM_DESCS,
		.libxdp_flags= 0,
		.xdp_flags   = XDP_FLAGS_DRV_MODE,
		.bind_flags  = XDP_USE_NEED_WAKEUP,
	},
	.u = NULL,
	.iface = NULL,
	.iface_queue = 0,
};

#ifndef MAX_PORTS
#define MAX_PORTS 64
#endif

#ifndef MAX_THREADS
#define MAX_THREADS 64
#endif

static struct umem_mgr *g_umem;

static struct port_params port_params[MAX_PORTS];
static struct port *ports[MAX_PORTS];
static u64 n_pkts_rx_hist[MAX_PORTS];
static u64 n_pkts_tx_hist[MAX_PORTS];
static int n_ports;

static pthread_t threads[MAX_THREADS];
static struct thread_data thread_data[MAX_THREADS];
static int n_threads;

static void
print_usage(char *prog_name)
{
	const char *usage =
		"Usage:\n"
		"\t%s -c CORE -i INTERFACE [ -q QUEUE ]\n"
		"\n"
		"-c CORE        CPU core to pin a forwarding thread. May be repeated.\n"
		"-i INTERFACE   Interface for a forwarding port. May be repeated.\n"
		"-q QUEUE       Queue index for the last specified interface (default 0).\n"
		"\n";
	printf(usage, prog_name);
}

static int
parse_args(int argc, char **argv)
{
	struct option lgopts[] = {
		{ NULL,  0, 0, 0 }
	};
	int opt, option_index;

	for (;;) {
		opt = getopt_long(argc, argv, "c:i:q:", lgopts, &option_index);
		if (opt == EOF) break;

		switch (opt) {
		case 'c':
			if (n_threads == MAX_THREADS) {
				printf("Max threads (%d) reached.\n", MAX_THREADS);
				return -1;
			}
			thread_data[n_threads].cpu_core_id = atoi(optarg);
			n_threads++;
			break;

		case 'i':
			if (n_ports == MAX_PORTS) {
				printf("Max ports (%d) reached.\n", MAX_PORTS);
				return -1;
			}
			port_params[n_ports].iface = optarg;
			port_params[n_ports].iface_queue = 0;
			n_ports++;
			break;

		case 'q':
			if (n_ports == 0) {
				printf("No port specified for queue.\n");
				return -1;
			}
			port_params[n_ports - 1].iface_queue = atoi(optarg);
			break;

		default:
			printf("Illegal argument.\n");
			return -1;
		}
	}

	optind = 1;

	if (!n_ports) {
		printf("No ports specified.\n");
		return -1;
	}
	if (!n_threads) {
		printf("No threads specified.\n");
		return -1;
	}
	if (n_ports % n_threads) {
		printf("Ports cannot be evenly distributed to threads.\n");
		return -1;
	}
	return 0;
}

static void
print_port(u32 port_id)
{
	struct port *port = ports[port_id];
	printf("Port %u: interface = %s, queue = %u\n",
	       port_id, port->params.iface, port->params.iface_queue);
}

static void
print_thread(u32 thread_id)
{
	struct thread_data *t = &thread_data[thread_id];
	u32 i;

	printf("Thread %u (CPU core %u): ",
	       thread_id, t->cpu_core_id);

	for (i = 0; i < t->n_ports_rx; i++) {
		struct port *port_rx = t->ports_rx[i];
		struct port *port_tx = t->ports_tx[i];

		printf("(%s, %u) -> (%s, %u)%s",
		       port_rx->params.iface, port_rx->params.iface_queue,
		       port_tx->params.iface, port_tx->params.iface_queue,
		       (i + 1 == t->n_ports_rx) ? "" : ", ");
	}
	printf("\n");
}

static void
print_port_stats_separator(void)
{
	printf("+-%4s-+-%12s-+-%13s-+-%12s-+-%13s-+\n",
	       "----", "------------", "-------------", "------------", "-------------");
}

static void
print_port_stats_header(void)
{
	print_port_stats_separator();
	printf("| %4s | %12s | %13s | %12s | %13s |\n",
	       "Port", "RX packets", "RX rate (pps)", "TX packets", "TX_rate (pps)");
	print_port_stats_separator();
}

static void
print_port_stats_trailer(void)
{
	print_port_stats_separator();
	printf("\n");
}

static void
print_port_stats(int port_id, u64 ns_diff)
{
	struct port *p = ports[port_id];
	double rx_pps = (p->n_pkts_rx - n_pkts_rx_hist[port_id]) * 1000000000. / ns_diff;
	double tx_pps = (p->n_pkts_tx - n_pkts_tx_hist[port_id]) * 1000000000. / ns_diff;

	printf("| %4d | %12llu | %13.0f | %12llu | %13.0f |\n",
	       port_id,
	       (unsigned long long)p->n_pkts_rx, rx_pps,
	       (unsigned long long)p->n_pkts_tx, tx_pps);

	n_pkts_rx_hist[port_id] = p->n_pkts_rx;
	n_pkts_tx_hist[port_id] = p->n_pkts_tx;
}

static void
print_port_stats_all(u64 ns_diff)
{
	print_port_stats_header();
	for (int i = 0; i < n_ports; i++)
		print_port_stats(i, ns_diff);
	print_port_stats_trailer();
}

static volatile int quit;

static void
signal_handler(int sig)
{
	(void)sig;
	quit = 1;
}

static void remove_xdp_program(void)
{
	for (int i = 0 ; i < n_ports; i++) {
		int ifindex = if_nametoindex(port_params[i].iface);
		struct xdp_multiprog *mp = xdp_multiprog__get_from_ifindex(ifindex);
		if (IS_ERR_OR_NULL(mp)) {
			printf("No XDP program loaded on %s\n", port_params[i].iface);
			continue;
		}
		int err = xdp_multiprog__detach(mp);
		if (err)
			printf("Unable to detach XDP program from %s: %s\n",
			       port_params[i].iface, strerror(-err));
	}
}

int main(int argc, char **argv)
{
	struct timespec ts;
	u64 ns0;

	/* Defaults */
	struct umem_mgr_params up = umem_params_default;
	struct xsk_umem_config umc = umem_cfg_default;
	for (int i = 0; i < MAX_PORTS; i++)
		memcpy(&port_params[i], &port_params_default, sizeof(struct port_params));

	/* Parse args */
	if (parse_args(argc, argv)) {
		print_usage(argv[0]);
		return -1;
	}

	/* Create global UMEM (shared by all sockets) */
	g_umem = umem_mgr_create(&up, &umc);
	if (!g_umem) {
		fprintf(stderr, "UMEM creation failed.\n");
		return -1;
	}
	printf("UMEM created: %u frames x %u bytes\n", up.n_frames, up.frame_size);

	/* Init ports */
	for (int i = 0; i < MAX_PORTS; i++)
		port_params[i].u = g_umem;

	for (int i = 0; i < n_ports; i++) {
		ports[i] = port_init(&port_params[i]);
		if (!ports[i]) {
			fprintf(stderr, "Port %d initialization failed.\n", i);
			return -1;
		}
		print_port(i);
	}
	printf("All ports created successfully.\n");

	/* Thread wiring: per thread, make a ring over its share of ports. */
	for (int i = 0; i < n_threads; i++) {
		struct thread_data *t = &thread_data[i];
		u32 n_ports_per_thread = n_ports / n_threads;

		for (u32 j = 0; j < n_ports_per_thread; j++) {
			t->ports_rx[j] = ports[i * n_ports_per_thread + j];
			t->ports_tx[j] = ports[i * n_ports_per_thread +
			                      (j + 1) % n_ports_per_thread];
		}
		t->n_ports_rx = n_ports_per_thread;
		print_thread(i);
	}

	/* Launch threads */
	for (int i = 0; i < n_threads; i++) {
		int status = pthread_create(&threads[i], NULL, thread_func, &thread_data[i]);
		if (status) {
			fprintf(stderr, "Thread %d creation failed: %s\n", i, strerror(status));
			return -1;
		}
	}
	printf("All threads created successfully.\n");

	/* Stats */
	signal(SIGINT,  signal_handler);
	signal(SIGTERM, signal_handler);
	signal(SIGABRT, signal_handler);

	clock_gettime(CLOCK_MONOTONIC, &ts);
	ns0 = (u64)ts.tv_sec * 1000000000ULL + (u64)ts.tv_nsec;
	while (!quit) {
		u64 ns1, ns_diff;
		sleep(1);
		clock_gettime(CLOCK_MONOTONIC, &ts);
		ns1 = (u64)ts.tv_sec * 1000000000ULL + (u64)ts.tv_nsec;
		ns_diff = ns1 - ns0;
		ns0 = ns1;
		print_port_stats_all(ns_diff);
	}

	/* Join & cleanup */
	printf("Quit.\n");
	for (int i = 0; i < n_threads; i++)
		thread_data[i].quit = 1;
	for (int i = 0; i < n_threads; i++)
		pthread_join(threads[i], NULL);

	for (int i = 0; i < n_ports; i++)
		port_free(ports[i]);

	umem_mgr_destroy(g_umem);

	remove_xdp_program();
	return 0;
}
