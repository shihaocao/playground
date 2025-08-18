## Playground

This project is a playground to try random things, both at the software implementation level,
and using AI at the same time.

## C++

Build:
```
./build.sh
```

Run:
```
./builddir/exp/targets/hello
```

Perf:
- perf script: Reads the current directory’s perf.data and prints human‑readable stack samples.
- ~/FlameGraph/stackcollapse-perf.pl: Collapses those samples into “folded” stack lines with counts.
- c++filt: Demangles C++ symbols in the folded stacks.
- ~/FlameGraph/flamegraph.pl: Turns the folded stacks into an SVG flame graph.
> hello.svg: Redirects the SVG output into hello.svg.
```
perf script | ~/repos/FlameGraph/stackcollapse-perf.pl | c++filt | ~/repos/FlameGraph/flamegraph.pl > outputs/hello.svg
```


#### Factorial Testing
```
./builddir/exp/targets/build-debug.sh
./builddir/exp/targets/factorial_file_in
```

Perf args, what do they mean?
- -F 99: sample at ~99 times per second (sampling frequency).
- -g: capture call stacks (for flame graphs/call graph analysis).

With Perf:
```
perf record -F 99 -g -- ./builddir/exp/targets/factorial_file_in
perf script | ~/repos/FlameGraph/stackcollapse-perf.pl | c++filt | ~/repos/FlameGraph/flamegraph.pl > outputs/factorial_file_in.svg
```