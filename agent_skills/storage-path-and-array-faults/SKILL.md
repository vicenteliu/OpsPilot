---
id: storage-path-and-array-faults
name: Storage path and array faults
trigger: Storage is failing or degraded — a datastore or LUN dropped, an iSCSI or NFS mount went stale or read-only, VMs froze or paused on a datastore, paths are down (APD or PDL), an array or ZFS pool is degraded and rebuilding or resilvering, a disk failed, storage latency spiked, or a volume filled up and everything on it stopped.
allowed_tools:
  - kb_search
trust: internal
---

# Storage path and array faults

Use this when storage is the suspected fault — a datastore that dropped, a mount
that went stale, an array that is degraded, or latency that has made everything
on a volume unusable.

One framing to lead with, because it decides the first move:

> **For IP storage, a storage fault is very often a network fault wearing
> storage clothes.** iSCSI and NFS run over the same switches as everything
> else, so "the datastore is gone" and "the path to the datastore is gone" are
> different problems with one symptom. Establish which before doing anything
> else — and if it is the path, hand off to `network-fault-isolation`, which is
> the skill for that.

## 0. Array, path, or consumer

Three questions, in this order. Each eliminates a third of the problem.

1. **Is the array itself healthy?** Read its own status first — pool or array
   state, failed members, controller alarms. If the array is degraded, stop
   reading the rest of this section and go to part 2.
2. **Can anything reach it?** One consumer affected or all of them? All
   consumers means the array or the path; one consumer means that host — its
   initiator, its VLAN, its NIC.
3. **Is the volume simply full?** A datastore or pool that has hit its limit
   freezes everything on it and reports as a hundred different faults. Check
   this early because it is cheap and it is common — and on a thin-provisioned
   or snapshot-heavy volume it arrives without anyone writing anything new.

## 1. Paths — the distinction that decides the response

When paths to a device fail, the two states look identical from the console and
mean opposite things:

| | What happened | What the host does | What it means for you |
|---|---|---|---|
| **All paths down (APD)** | the host cannot reach the device, and **nothing told it the device is gone** | keeps retrying, holds I/O, VMs hang | could be a cable, a switch, a controller rebooting. It may come back. **Do not tear anything down yet** |
| **Permanent device loss (PDL)** | the array **explicitly reported** the device is gone | stops retrying | it is not coming back on this path. Now action is warranted |

Getting these backwards costs both ways: treat a PDL as an APD and you wait
forever for something that will never return; treat an APD as a PDL and you tear
down running workloads over a thirty-second blip.

**If it is a path problem, work it as a network problem:**

- **The storage VLAN and its MTU.** Jumbo frames configured on some hops and not
  others is the classic IP-storage fault: it works, then hangs under load, and
  it looks like the array is slow. See `network-fault-isolation`, section 8.
- **The initiator side** — is the session actually established? For iSCSI, check
  the portal, the target name, and whether authentication is being rejected
  rather than the target being unreachable. A refused login and an unreachable
  portal are the storage equivalent of refused-versus-timeout.
- **Multipath.** How many paths are meant to exist, and how many are active? A
  quiet degradation to a single path is invisible until that one fails too, and
  then it presents as a sudden total loss with no apparent cause.

## 2. A degraded array or pool

**Read the state before touching any hardware.** Which member failed, which are
healthy, and is a rebuild or resilver already running.

- **The rebuild window is the dangerous period, not the failure.** The array
  survived losing one member. During a rebuild every remaining member is read
  end to end under load, which is exactly when a second weakness surfaces —
  and on large drives an unrecoverable read error during that pass is the
  realistic failure mode, not a second whole disk dying.
- **This is why parity choice is a capacity-versus-risk decision**, not a
  default. Single parity on large modern drives means a rebuild is a
  single-failure-away window that lasts hours to days. Double parity buys a
  second one. On smaller drives in a small enclosure single parity remains
  defensible — the honest answer names the drive count and capacity rather than
  declaring a level right or wrong.
- **Confirm it is really the drive.** A cable, a backplane slot, or a controller
  can present exactly as a failed member. Replacing the wrong thing costs a
  second rebuild window on top of the first.
- **A running rebuild is slow, and that is not a second fault.** Latency
  complaints during a resilver are expected. Reporting them as a new problem
  sends someone chasing a ghost.

⛔ **Never pull a disk to see what happens.** In a degraded array that is the
second failure.

## 3. Latency, not loss

Everything is up and everything is slow:

- **Is one consumer saturating it?** A backup, a clone, a migration, or a
  runaway VM. Find the loudest before assuming the array is at fault.
- **Snapshots.** A long snapshot chain costs read performance and consumes space
  that nobody accounted for. On a copy-on-write pool, snapshots and their space
  are the usual explanation for a volume that filled up with no new data written.
- **Free space.** Copy-on-write and thin-provisioned storage degrades sharply
  as it approaches full — well before it reports being out of space. "Slow" and
  "nearly full" are frequently the same fault.
- **Queue depth and path count** — see part 1. Silently running on one path
  halves or worse the available throughput.

## 4. Where snapshots come from

Worth establishing early, because it changes who owns the fix and what a restore
can even do: a snapshot taken by the **storage layer** and a snapshot taken by
the **hypervisor** are different objects with different costs, different
consistency guarantees, and different recovery paths. Know which one exists here
before promising anything about rolling back.

## When to stop

- **Any change to the array** — replacing a member, starting or cancelling a
  rebuild, clearing a failed or foreign state, changing a parity level. All
  stops, without exception.
- **Any change to the storage path** — multipath configuration, MTU, VLAN,
  initiator or target configuration. Those are network changes with storage
  consequences, and they are stops in `network-fault-isolation` too.
- **Anything that deletes data to free space**, including snapshots. Space
  pressure during an incident is exactly when someone deletes the snapshot that
  was the recovery plan.
- **Data integrity is in question.** Stop immediately and escalate. This is the
  one domain where continuing to poke is worse than waiting.
- **Two full passes with no new evidence.** Say what has been eliminated and
  hand over.

## Never

- **Never pull, reseat, or replace a disk** as a diagnostic step, and never in a
  degraded array without confirming which physical member is which.
- **Never clear a failed, foreign, or offline state** to make an array look
  healthy. That state is the record of what happened.
- **Never force-online or force-mount a degraded pool or volume.**
- **Never delete snapshots to free space during an incident** without knowing
  what depends on them.
- **Never change MTU on a live storage network.**
- **Never cancel a running rebuild** to relieve latency.
- **Never assume the array is at fault because the symptom appeared there.** For
  IP storage the path is a network, and that is where the fault usually is.
