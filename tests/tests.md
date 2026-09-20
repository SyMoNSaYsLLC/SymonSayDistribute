# tests

What proves `symondevice`, and — the part worth reading — which of these tests can actually fail.

Run from the branch root:

    python3 -m pytest tests/ -q --color=no

The `-m` form is what puts the root on `sys.path`, which is how `service` and `symondevice`
become importable. Result on this host: **43 passed, rc 0**, with no skips — every hardware test
found its hardware and asserted against it.

## The rule this file is written under

**A test that would pass whether or not the code is right has tested nothing.** Two shapes of
that show up constantly in a hardware inventory, and both are guarded against explicitly:

- **A pattern that matches nothing.** `test_the_mac_pattern_this_file_searches_with_actually_matches_a_mac`
  runs first and proves the expression matches `0a:1b:2c:3d:4e:5f`, matches an upper-case
  address in a sentence, and does **not** match the three-octet prefix this component legitimately
  returns or a `HH:MM:SS` timestamp. Without that, the MAC test is a search for something the
  expression could never find.
- **A skip that hides a broken answer.** Every hardware test skips on the **device being absent**
  and never on the answer being empty. `test_sensor_readings_...` skips when `/sys/class/hwmon`
  publishes no readings at all; it does not skip when readings come back without labels, values
  or paths — that is a failure.

## Privacy: the two tests that had to be built differently

**A MAC has a shape, so a pattern finds it.** `test_no_full_mac_address_appears_in_any_response`
decodes every route's JSON and searches all of it. The permitted half is checked too:
`test_the_oui_prefix_is_returned_and_is_only_three_octets` requires an interface *with* a
hardware address before it asserts anything, so it cannot pass on a host with none.

**A serial has no shape**, so a pattern could never find one. `_real_serials()` reads the actual
serial values this host publishes — six of them, across USB devices, the battery entry and two
disks — and asserts those exact strings appear in no response. Two refinements were forced by the
first run and both are recorded in the file, because each is the kind of thing that gets a real
check weakened until it stops checking:

- a **root hub** publishes its controller's PCI bus address in its `serial` attribute. That is
  not an identifier of anything, and it legitimately appears inside every device path under that
  controller. Root hubs and PCI-address-shaped values are excluded by name and by pattern.
- `address` on a PCI device is the **bus address**, a technical identifier software is
  configured with. It is not in the forbidden-key set. The hardware address is checked by field
  name on the objects that could carry one, in
  `test_no_network_interface_object_carries_a_hardware_address_field` — which catches a field
  that is empty on this host and populated on another, where a value check would not.

No assertion message in this file contains a value it read.

## The constructed tree

`_fake_pci()` builds three devices under pytest's `tmp_path`. Nothing in this file writes outside
the directory pytest hands it, no path is composed by hand, and `/sys` is never written to.

| Device | Case | Asserted |
|---|---|---|
| `0000:00:01.0` | `driver` symlink, target exists | driver name, `driver_target_exists: true` |
| `0000:00:02.0` | **no `driver` entry at all** | `driver is None`, **and not the literal string `driver`**, present in `devices`, present in `unbound` |
| `0000:00:03.0` | `driver` symlink, target gone | driver name still reported, `driver_target_exists: false` |

The middle row is the whole point. `realpath` canonicalises a missing last component and returns
it, so an implementation built that way reports the driver as `driver` — and the assertion that
catches it carries that explanation in its message, so whoever hits it in future does not have to
rediscover why.

`test_the_unbound_device_reaches_owned_by_rather_than_being_absorbed` then drives the same tree
through `owned_by()`, because reporting a device correctly and then dropping it from the coverage
map is the same failure one layer up.

## The zero-size device, tested twice

Once against a **constructed** tree, so the claim is falsifiable on any machine including one
with nothing of the kind plugged in; once against **this host**, skipping if no device here
reports zero bytes. The real-host test additionally requires that a zero-byte device has a driver
bound — both, or neither, because a device reporting zero bytes *and* no driver is a different
finding from a card reader with no card.

## Coverage must find a gap

`test_owned_by_names_at_least_one_unowned_hardware_class` asserts `full_coverage is False` and
that every unowned entry carries `owner: null`, an `inventoried_by`, a reason and evidence.
`test_an_unowned_class_is_not_also_claimed_as_owned` asserts the two lists do not intersect, and
`test_at_least_one_unowned_class_names_real_hardware_on_this_host` requires at least one of them
to name actual hardware — without it, `unowned` could be six labels with nothing behind them.

## Evidence, discovered rather than listed

`test_every_public_capability_returns_its_evidence` finds the public callables **from the module**
and asserts its own list matches, so a capability added without evidence fails here rather than
being quietly missed. It then asserts `rc` is derived — `rc == 1` exactly when `unreadable` is
non-empty — and that `command` and `argv` are `null`, because this module runs no program and an
evidence block claiming a process exit code it never obtained would be worse than none.

`test_an_unreadable_source_sets_rc_to_one` points a source at nothing and requires `rc` to change.
An `rc` that is always 0 is decoration.

## Read-only, checked rather than promised

`test_nothing_in_the_module_runs_a_program_or_reaches_a_shell` refuses `subprocess`, `os.system`,
`shell=True`, `os.popen` and friends in the capability module's source.

`test_nothing_in_the_module_opens_a_path_for_writing` extracts the **mode argument of every
`open()` call** and requires each to be `r` — and asserts it found at least one to check, so it
cannot pass by finding nothing.

## The bind address decides, §3.2a

| Test | Asserts |
|---|---|
| `test_loopback_needs_no_token` | with **no** `SYM_DEVICE_TOKEN` set anywhere, all nine routes answer `200` on a loopback bind. Unset must not mean dead |
| `test_the_default_bind_with_no_variable_set_is_loopback` | no variables set at all still binds loopback; the default decides, not the operator remembering |
| `test_off_loopback_with_no_token_is_503` | `SYM_DEVICE_HOST=0.0.0.0` with no token returns `503` on all nine, and `health` stays `200` |
| `test_off_loopback_with_a_wrong_token_is_401` | the comparison actually runs |
| `test_a_hostname_that_cannot_be_proved_loopback_is_treated_as_reachable` | `localhost` and `::1` are loopback; a name that cannot be proved so is not |

The `client` fixture binds **off-loopback deliberately**. On a loopback bind the guard returns
before comparing anything, so every authenticated test in the file would pass with a wrong token
or with none — the fixture would have disabled the thing it exists to exercise.

## Where this leads

Nowhere onward. The chain that began at [`symondevice.md`](../symondevice.md) and ran through
[`symondevice/`](../symondevice/symondevice.md) ends here, because a passing suite is the last
thing between this component and a release: there is no further directory, and nothing downstream
consumes these tests. §3.7 requires that to be stated rather than left as an unexplained absence.
