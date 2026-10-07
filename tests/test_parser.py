from app.whatsapp.parser import MAX_TEXT_CHARS, parse_incoming


def test_parse_valid_text_message():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "923001234567",
                                    "id": "wamid.TEST001",
                                    "type": "text",
                                    "text": {
                                        "body": "  Do you have a laptop?  "
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ],
    }

    messages = parse_incoming(payload)

    assert len(messages) == 1
    assert messages[0].message_id == "wamid.TEST001"
    assert messages[0].phone == "+923001234567"
    assert messages[0].text == "Do you have a laptop?"


def test_parser_ignores_image_message():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "923001234567",
                                    "id": "wamid.IMAGE",
                                    "type": "image",
                                    "image": {
                                        "id": "image-id",
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    assert parse_incoming(payload) == []


def test_parser_ignores_audio_message():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "923001234567",
                                    "id": "wamid.AUDIO",
                                    "type": "audio",
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    assert parse_incoming(payload) == []


def test_parser_ignores_empty_text():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "923001234567",
                                    "id": "wamid.EMPTY",
                                    "type": "text",
                                    "text": {
                                        "body": "   ",
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    assert parse_incoming(payload) == []


def test_parser_normalizes_phone_number():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "+92 300-1234567",
                                    "id": "wamid.PHONE",
                                    "type": "text",
                                    "text": {
                                        "body": "Hello",
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    messages = parse_incoming(payload)

    assert messages[0].phone == "+923001234567"


def test_parser_rejects_invalid_phone():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "123",
                                    "id": "wamid.BADPHONE",
                                    "type": "text",
                                    "text": {
                                        "body": "Hello",
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    assert parse_incoming(payload) == []


def test_parser_limits_text_length():
    long_text = "x" * (MAX_TEXT_CHARS + 500)

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "923001234567",
                                    "id": "wamid.LONG",
                                    "type": "text",
                                    "text": {
                                        "body": long_text,
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    messages = parse_incoming(payload)

    assert len(messages) == 1
    assert len(messages[0].text) == MAX_TEXT_CHARS


def test_parser_handles_malformed_payload():
    assert parse_incoming({"something": "invalid"}) == []


def test_parser_handles_status_only_webhook():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [
                                {
                                    "id": "wamid.STATUS",
                                    "status": "delivered",
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    assert parse_incoming(payload) == []