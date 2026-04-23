/**
 * Index map for the 32-dim `stream1_last` vector emitted by the control plane.
 *
 * Verified against `data/preprocessing.py::flatten_telemetry`:
 *
 *   STAT_GROUPS = [
 *     "cpu", "memory", "processes", "network_connections",
 *     "dest_ip_entropy", "io_read_rate", "io_write_rate",
 *   ]  // 7 groups * 4 stats (mean,max,min,std) = 28
 *   + [syscall_entropy, unique_syscalls, total_syscalls, sample_count] = 4
 *   // total = 32
 *
 * Index layout (mean stat for each group sits at group_offset * 4):
 *   0  cpu.mean                   (shown as CPU sparkline)
 *   1..3  cpu.max/min/std
 *   4  memory.mean                (shown as Memory sparkline)
 *   5..7  memory.max/min/std
 *   8  processes.mean
 *   9..11 processes.max/min/std
 *   12 network_connections.mean   (shown as Network sparkline)
 *   13..15 network_connections.max/min/std
 *   16..19 dest_ip_entropy.{mean,max,min,std}
 *   20..23 io_read_rate.{mean,max,min,std}
 *   24..27 io_write_rate.{mean,max,min,std}
 *   28 syscall_entropy
 *   29 unique_syscalls
 *   30 total_syscalls
 *   31 sample_count
 */
export const FEATURE_INDEX = {
  cpu: 0,
  mem: 4,
  net: 12,
} as const;
