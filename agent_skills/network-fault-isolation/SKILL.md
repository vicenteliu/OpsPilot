---
id: network-fault-isolation
name: Cross-layer network fault isolation
trigger: Something is unreachable, timing out, intermittent, or unexpectedly slow across the network — a share, mount, service, or host. Covers connection refused versus timeout, DNS resolving but connections failing, name resolution returning the wrong address, large file copies or transfers hanging while small ones work (MTU), packet loss, asymmetric routing, a firewall or ACL silently dropping traffic, and flapping or error-counting links.
allowed_tools:
  - kb_search
trust: internal
---

# Cross-layer network fault isolation

Use this when the symptom is "X cannot reach Y" and nobody knows yet whether the
fault is naming, routing, switching, filtering, the service itself, or the wire.

This is a **method**, not a tool list. The method has one rule:

> **Every check must eliminate something.** A check that tells you nothing when
> it fails is a wasted round trip. Order the checks so each one cuts the
> remaining search space roughly in half, and stop as soon as the fault is
> localised to something you do not own.

Everything here is diagnosis. Nothing in it changes a device's configuration —
see **Never**, which is short and absolute.

## 0. Bisect by pattern before touching anything

Ask two questions and the answer usually names the layer for free:

| | one destination | many destinations |
|---|---|---|
| **one client** | the pair, or the service on that port | the client — its config, its link, its resolver |
| **many clients** | the destination, or the service | shared infrastructure — DNS, DHCP, routing, a trunk |

Then: **when did it last work, and what changed?** Networks do not decay
gracefully; they change and then break. A change window is worth more than an
hour of packet capture.

## 1. Separate naming from reachability — always first

Try the destination by **IP address** directly.

- **IP works, name does not** → this is name resolution, not the network. Stop
  going down the network path; go to the resolver, the search domain, and what
  the client was handed by DHCP.
- **Neither works** → carry on below.
- **Name resolves to the wrong address** → stale record, split-horizon, or a
  local override. Check what the client actually resolved, not what the zone
  says it should.

This step is first because "the network is down" is a DNS problem more often
than it is anything else, and every check below is wasted effort if the name was
the fault.

## 2. Layer 3 — is there a path

- Can the client reach its **default gateway**?
- What does the **routing table** say the next hop for that destination is? A
  wrong or missing route is common after a VPN connects, a second interface
  comes up, or a container network is added.
- Is the destination on the **same subnet** or a different one? That single fact
  decides whether step 3 or the routed path is where the fault can live.

⚠️ **A failed ping is not proof of unreachability.** ICMP is filtered as a matter
of routine. Ping succeeding is strong evidence; ping failing is weak evidence.

## 3. Layer 2 — only if the destination is on the same subnet

On the same subnet there is no routing to be wrong: address resolution decides
everything.

- Look at the client's **neighbour / ARP table** for the destination. A complete
  entry means the two have exchanged frames — the problem is above layer 2. An
  **incomplete entry means nothing answered**, which points at VLAN assignment,
  a switch port, or the destination being down.
- Two devices in the same IP subnet but different VLANs will never resolve each
  other. This looks exactly like "the host is down" and is not.
- A duplicate address, or two answers for one address, shows up here and almost
  nowhere else.

## 4. Layer 4 — the most informative single test

Test the **specific port**, and read the failure mode rather than the fact of
failure:

- **Connection refused** → something answered. The host is reachable and the
  stack is fine; the service is not listening, or is listening on a different
  address or port. This is a service problem, not a network problem.
- **Timeout, no response at all** → nothing answered. Something is dropping
  silently: a firewall rule, an ACL, a blackhole route, or a host that is down.
- **Connection resets mid-session** → the path works and something is
  interrupting it: an idle timeout, a stateful device that lost the flow, an
  application-level close.

On the destination, confirm what is actually **listening and on which address** —
a service bound to loopback is unreachable from anywhere else and produces a
perfect "network problem".

## 5. Where does the path stop

Trace the path and note the hop it dies at. Then consider the **return path**
separately: a request that arrives and a reply that never comes back is
asymmetric routing or a one-directional filter, and it looks identical to "the
destination is ignoring us" from the client side.

## 6. Filtering

If the pattern says one destination and many clients, or a specific port only,
suspect a rule.

The cheap discriminator: **test from a host on the same segment as the
destination.** If it works there and not from outside, the fault is on the path,
not at either end — and you have localised it without touching a single rule.

## 7. Capture — expensive, and only with a question

Only now, and only with something specific to look for. On both ends, filtered
to the conversation, bounded in time or size.

The one thing capture answers that nothing else does: **did the packet arrive,
and did a reply leave?** That splits the problem three ways — never sent, lost
in transit, or reply lost — and each is a different owner.

## 8. Two symptom shapes that skip the ladder

- **Works for small things, hangs on large transfers** — file copies stall,
  mounts hang, a session opens then freezes. This is an **MTU** problem: the
  path cannot carry a full-size frame and the mechanism that would have
  discovered that is being filtered. Common on tunnels, on storage networks with
  jumbo frames configured unevenly, and after a VPN is introduced.
- **Intermittent or slow rather than broken** — check interface **error counters
  and link stability** early instead of last. A duplex or speed mismatch, a
  failing cable or optic, or a flapping link produces "the network is slow"
  and never produces a clean failure to isolate.

## When to stop

- **The fault is localised to a device or segment someone else owns.** Hand it
  over with the evidence: what was tried, what it proved, which layer is
  eliminated. That is the deliverable, not a fix.
- **The fix is a configuration change** — a firewall rule, a route, a VLAN, an
  MTU, an interface setting. Those are all stops, without exception.
- **The evidence points at hardware** — errors on a port, a failing optic. Collect
  the counters and hand over.
- **Two full passes produced no new evidence.** Say what has been ruled out and
  escalate. Running the same checks more carefully is not progress.

## Never

- **Never change a firewall rule or ACL to test a theory.** If it starts working
  you have learned almost nothing about *why*, and the change outlives the test —
  this is how permanent holes get opened by people who meant to close them again.
- **Never restart a switch, router, gateway, or firewall to clear a fault.** It
  destroys the state that was about to explain the problem, and it is an outage
  for everyone else on it.
- **Never flush ARP or neighbour caches on production equipment as a diagnostic.**
  That table was the evidence.
- **Never change MTU globally** to fix one symptom.
- **Never conclude a host is down from ICMP alone.**
- **Never start an unbounded capture on a busy interface.** Bound it by filter,
  by time, or by size — an unfiltered capture fills the disk and buries the two
  packets that mattered.
