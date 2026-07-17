from overture2gmns.rules import as_rule_list, coerce_struct


NUMPY_REPR = (
    "[{'connector_id': 'abc', 'at': 0.0}\n"
    " {'connector_id': 'def', 'at': 0.5}\n"
    " {'connector_id': 'ghi', 'at': 1.0}]"
)


def test_coerce_numpy_repr_connectors():
    parsed = coerce_struct(NUMPY_REPR)
    assert isinstance(parsed, list)
    assert [item["connector_id"] for item in parsed] == ["abc", "def", "ghi"]


def test_coerce_valid_json_passthrough():
    assert coerce_struct('[{"at": 0.25}]') == [{"at": 0.25}]


def test_coerce_repr_with_none_and_nested_array():
    text = ("[{'access_type': 'denied', 'when': {'heading': 'backward', 'mode': None}, "
            "'between': array([0. , 0.5])}]")
    parsed = coerce_struct(text)
    assert parsed[0]["access_type"] == "denied"
    assert parsed[0]["between"] == [0.0, 0.5]


def test_coerce_leaves_plain_strings_alone():
    assert coerce_struct("Main Street") == "Main Street"
    assert coerce_struct("") == ""
    assert coerce_struct(None) is None


def test_as_rule_list_accepts_repr_strings():
    rules = as_rule_list(NUMPY_REPR)
    assert len(rules) == 3
    assert rules[2]["at"] == 1.0


def test_oneway_rule_with_materialized_none_scopes():
    """Real-world Overture shape: every 'when' key present, most set to None.

    The backward denial must still apply — None-valued scopes are not
    conditions (regression: all motorways came out bidirectional).
    """
    from overture2gmns.rules import access_allowed

    access = (
        "[{'access_type': 'denied', 'when': {'during': None, 'heading': 'backward', "
        "'using': None, 'recognized': None, 'mode': None, 'vehicle': None}, "
        "'between': None}\n"
        " {'access_type': 'denied', 'when': {'during': None, 'heading': None, "
        "'using': None, 'recognized': None, 'mode': array(['bicycle'], dtype=object), "
        "'vehicle': None}, 'between': None}]"
    )
    common = dict(lr=0.5, mode="auto", default_allowed=True)
    assert access_allowed(access, heading="forward", **common) is True
    assert access_allowed(access, heading="backward", **common) is False
    # The bicycle-only denial must not leak into auto but must hit bike.
    assert access_allowed(access, heading="forward", lr=0.5, mode="bike",
                          default_allowed=True) is False
