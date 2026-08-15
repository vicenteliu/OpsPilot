---
id: vsphere-cluster-faults
name: vSphere cluster faults
trigger: Something is wrong at the vSphere cluster level — a VM will not migrate, VMs did not restart after a host failure, the cluster looks unbalanced, hosts powered themselves off, or Fault Tolerance did not protect a workload.
allowed_tools:
  - kb_search
trust: internal
---

# vSphere cluster faults

Use this when the problem is the **cluster**, not a single VM or a single host.
The tell is that the symptom involves two or more hosts: a migration between
them, a restart across them, a balance among them, or a protected pair spanning
them.

Everything below is diagnosis. **Suggest, and stop where the section says
stop** — every one of these stops is a change that alters cluster-wide behaviour
or requires powering something off, and neither is yours to decide.

Cluster feature behaviour changes between vSphere releases. Establish the
version first and search the KB for it before quoting any specific limit; treat
version-specific numbers in this file as prompts to check, not as facts to
recite.

## 0. Scope it first

- **Which version?** Behaviour, and especially DRS, differs materially across
  6.x and 7.x+.
- **How many hosts are involved, and is it repeatable?** One VM failing once is
  not a cluster fault.
- **What changed?** A host added, a firmware update, a new rule, a licence
  change, a network change. Cluster faults are overwhelmingly caused by a change
  to the cluster, not by decay.
- Then take the branch that matches the symptom.

## A. A VM will not migrate

Work these in order — the list is roughly ordered by how often each is the real
cause.

1. **CPU compatibility.** Different vendors — Intel and AMD — cannot vMotion at
   all, and no setting bridges that. Different generations of the *same* vendor
   are what EVC exists to mask.
2. **A device tying the VM to its host.** A mounted host-local ISO or CD, a
   passthrough PCI device, an attached physical USB device without
   vMotion-capable passthrough, a host-local serial or parallel port. Any of
   these pins the VM.
3. **CPU affinity set on the VM.** Scheduling affinity pins a VM to physical
   cores on one host and blocks migration.
4. **Networking at the destination.** The VM's port group must exist and be
   equivalent on the destination host; on a distributed switch, the same
   dvPortGroup must reach it.
5. **The vMotion network itself.** The VMkernel adapter must have the vMotion
   service enabled on *both* hosts, and the two must actually reach each other.
6. **Storage visibility.** The destination must see the VM's datastore, unless
   this is deliberately a migration without shared storage — which has its own
   requirements and is much slower.
7. **Resources and reservations at the destination.** A reservation the
   destination cannot satisfy blocks the move, and reads as an obscure error.

**Stop and hand over** if the fix is an EVC baseline change. Raising or lowering
a cluster's baseline affects every VM in it and generally requires power cycles
to take effect — that is a maintenance-window decision.

## B. VMs did not restart after a host failed

HA restarting a VM is a crash and a boot elsewhere, not a seamless move.
Expect downtime; the question is only why there was none of the restart part.

1. **Admission control.** If the cluster cannot guarantee the configured
   failover capacity, power-on is refused. This is HA working as designed, and
   it is the most common answer.
2. **A "must" VM-Host affinity rule.** HA honours must-rules, so a VM whose
   permitted hosts are all gone will not be restarted anywhere. Should-rules do
   not have this effect.
3. **Datastore heartbeating said partition, not failure.** HA distinguishes a
   dead host from an isolated one partly by whether it is still writing to
   shared storage. A host that lost only its management network may have been
   correctly judged alive.
4. **Isolation response.** What the cluster was configured to do to VMs on an
   isolated host — leave them running, power them off, or shut them down — may
   simply be what happened.
5. **Datastore reachability from the survivors.** A VM whose datastore only the
   dead host could see cannot restart elsewhere.
6. **The agent's own health** on the surviving hosts.
7. **Host monitoring is not guest monitoring.** If the guest OS hung but the
   host stayed up, only VM Monitoring — which watches the guest heartbeat —
   would have acted. Host failover never sees a guest-level hang.

**Stop and hand over** before changing admission control or deleting an affinity
rule. Both silently remove a protection someone chose, and the affinity rule in
particular usually encodes a licensing or availability constraint invisible from
inside vCenter.

## C. The cluster looks unbalanced

1. **Automation level.** On manual or partially-automated, DRS produces
   recommendations and waits. An operator finding a long list of unapplied
   recommendations has found the answer.
2. **Migration threshold.** A conservative threshold acts only on large
   imbalances by design.
3. **Anything from branch A.** A VM that cannot vMotion cannot be balanced, and
   one pinned VM can account for the whole picture.
4. **Affinity and anti-affinity rules** constraining placement.
5. **Check what "balanced" means in this version.** Newer DRS is workload-centric
   — it reasons about whether each VM is getting what it needs, not about
   levelling host CPU percentages. A cluster with uneven host utilisation and
   every VM served is not a fault, and this is the most common false alarm in
   this branch. Confirm the version's model against the KB before calling it
   broken.

**Stop** at recommending a rule or threshold change. Applying an individual DRS
recommendation is ordinary work; changing the policy that generates them is not.

## D. Hosts powered themselves off

This is usually power management doing its job: it consolidates VMs onto fewer
hosts at low load and powers the rest down, and it rides on DRS.

- If hosts went down and load was low, that is the feature.
- If a host will not come back, the fault is almost always in the
  out-of-band path used to wake it — the BMC credentials, or wake-on-LAN
  reachability — not in the cluster.
- If load spiked and response was slow, the cost is the time it takes to power a
  host back on and admit VMs to it.

**Stop and hand over** the decision to disable power management. It is a
capacity-versus-power trade someone made deliberately.

## E. Fault Tolerance did not protect the workload

First establish what it was expected to protect against, because this is the
question most often answered wrongly:

> **FT protects against the loss of a host. It does not protect against the
> guest OS or the application failing.** The secondary executes the same
> instructions as the primary — so a guest panic, a corrupted database, or an
> application crash happens identically on both copies at the same moment. If
> the workload failed rather than the hardware, FT was never the control that
> was going to help.

If a host genuinely was lost and the workload still went down:

1. **The FT logging network.** It carries continuous state between the pair and
   is bandwidth-hungry and latency-sensitive; a saturated or shared link
   degrades or drops protection.
2. **No compatible host for a new secondary.** After a failover the surviving
   VM runs unprotected until a secondary is re-created somewhere. If nowhere is
   eligible, it stays unprotected — and the cluster is one failure from an
   outage while looking healthy.
3. **Configuration limits.** vCPU count and other limits are version- and
   licence-dependent; check them rather than assuming.
4. **HA must be enabled** on the cluster for FT to operate.
5. **Resource cost.** The pair consumes roughly double. A cluster sized without
   accounting for that may not be able to place the secondary.

## When to stop

Stop and hand the problem to a person when any of these is true:

- **The fix is a policy change** — EVC baseline, admission control, affinity
  rules, DRS automation or threshold, power management. These change how the
  cluster behaves for everything in it.
- **The fix requires powering off or restarting anything** that is currently
  running.
- **The evidence points at hardware, firmware, or a vendor defect.** Collect the
  evidence, then open a case.
- **Two full passes have produced no new evidence.** Repeating the same checks
  more carefully is not progress; say what was ruled out and escalate.

## Never

- **Never change an EVC baseline.** It can strand running VMs and force power
  cycles across the cluster.
- **Never disable or relax admission control**, even temporarily to power
  something on. That removes the failover capacity the cluster was sized for,
  and nothing will report it later.
- **Never delete or edit an affinity or anti-affinity rule.** They usually encode
  a constraint — licensing, availability, physical separation — that is not
  visible from inside vCenter.
- **Never power off, reset, or migrate a running VM** as a diagnostic step.
- **Never disable HA or FT** to make an error message go away.
- **Never conclude a host is dead from one failed ping.** Distinguishing a dead
  host from an isolated one is exactly what datastore heartbeating exists for,
  and getting it wrong is how a split brain starts.
