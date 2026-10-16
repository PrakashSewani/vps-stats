# Recorded fixtures

Real output, not synthetic. Recorded 2026-10-16 (IST) so the exporter's maths can be
asserted against numbers that actually came off the machines.

| File | Host | What it is |
|---|---|---|
| `proc_stat_a.txt` | hermes-vps (Ubuntu 26.04, 1 vCPU) | `/proc/stat` snapshot, the earlier of a pair |
| `proc_stat_b.txt` | hermes-vps | the same file **16 s later** - the pair is what makes the CPU delta deterministic |
| `proc_meminfo.txt` | hermes-vps | `/proc/meminfo` |
| `proc_loadavg.txt` | hermes-vps | `/proc/loadavg` |
| `mac_probe_raw.txt` | Prakash's MacBook Air (M3, 16 GB) | one full probe response: `KEY=value` lines, then `top -l 2 -n 0 -s 1`, `vm_stat`, `df -k` |

`mac_probe_raw.txt` is a single captured ssh response, so the Mac parser can be fed
exactly what the real Mac sent - including the wide `'` in the hostname, which is there
on purpose: the pipeline must survive non-ASCII.

Re-record on either host with:

```sh
# VPS
cp /proc/stat  tests/fixtures/proc_stat_a.txt; sleep 16; cp /proc/stat tests/fixtures/proc_stat_b.txt
cp /proc/meminfo tests/fixtures/proc_meminfo.txt; cp /proc/loadavg tests/fixtures/proc_loadavg.txt
```

Expected values derived from these fixtures live in `tests/test_exporter.py`.
