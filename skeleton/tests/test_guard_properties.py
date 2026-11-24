"""Property tests for the read-only guard."""

from hypothesis import given, settings
from hypothesis import strategies as st

from seance.guard import READ_TOOLS, Allowed, Read_Only_Guard, Rejected
from tests.fakes import Fake_Adapter

write_tool_names = st.text(max_size=40).filter(lambda name: name not in READ_TOOLS)

json_scalars = st.none() | st.booleans() | st.integers() | st.floats() | st.text(max_size=20)
arg_dicts = st.dictionaries(st.text(max_size=20), json_scalars, max_size=6)


def _gated_call(guard: Read_Only_Guard, adapter: Fake_Adapter, name: str, args: dict) -> object:
    """Model the server: touch the adapter only when the guard allows the call."""
    result = guard.check(name, args)
    if isinstance(result, Allowed):
        adapter.connect()
    return result


# Feature: skeleton-core, Property 5
# **Validates: Requirements 4.1, 4.2, 4.3**
@settings(max_examples=200)
@given(name=write_tool_names, args=arg_dicts)
def test_guard_rejects_every_write_request_without_calling_adapter(
    name: str, args: dict[str, object]
) -> None:
    adapter = Fake_Adapter()
    guard = Read_Only_Guard()

    result = _gated_call(guard, adapter, name, args)

    assert isinstance(result, Rejected)
    assert "read-only" in result.message
    assert "No change was made" in result.message
    assert adapter.call_count == 0


# Feature: skeleton-core, Property 6
# **Validates: Requirements 4.5**
@settings(max_examples=200)
@given(
    opted_in=st.frozensets(write_tool_names, max_size=8),
    name=write_tool_names,
    args=arg_dicts,
)
def test_only_opted_in_tools_are_allowed_to_write(
    opted_in: frozenset[str], name: str, args: dict[str, object]
) -> None:
    guard = Read_Only_Guard(opted_in)
    result = guard.check(name, args)
    if name in opted_in:
        assert isinstance(result, Allowed)
    else:
        assert isinstance(result, Rejected)
    for read_tool in READ_TOOLS:
        assert isinstance(guard.check(read_tool, args), Allowed)
