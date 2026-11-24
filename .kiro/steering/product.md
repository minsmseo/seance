# Product

## What this is

Seance is a skeleton for building read-only MCP servers on top of legacy device protocols. Old machines speak protocols from the 1970s and 1980s. AI agents speak MCP. Seance sits between them so an agent can ask a forty-year-old controller what it is doing.

The repository ships the skeleton plus two applications built from it:

1. `apps/modbus` exposes a simulated factory line over Modbus TCP.
2. `apps/snmp` exposes simulated network gear over SNMP.

The two apps share no protocol code. Everything they have in common lives in `skeleton/`.

## Who it is for

Engineers who maintain equipment that cannot be replaced and cannot be reached by modern tooling: plant engineers, lab technicians, small IT teams.

## Principles

- Read-only by default. The skeleton refuses every write operation unless an adapter author opts in explicitly per tool. A wrong write to real equipment can injure people.
- Every call is logged: who asked, which device, which address, what came back.
- A new protocol should take one adapter file and one config file. If it takes more, the skeleton is wrong.
- Simulators ship with every app so that anyone can run it without hardware.
- Values returned to the agent always carry a unit and a timestamp.

## Theme

The project is a Kiroween hackathon entry. The interface uses a seance motif: devices are spirits, a poll is a summoning, a timeout is silence from the other side. The motif must never hide information. Device names, values and errors stay plain and readable.

## Out of scope

- Writing to devices in the demo apps
- Authentication against real industrial networks
- Protocols beyond the two demo apps
