"""Parsing tests for the Wi-Fi probe.

The commands cannot run off macOS, but their output shapes are stable, so the
parsing is pinned here against real captures.
"""

from mcp_server.tools.system import (
    LOCATION_HINT,
    parse_link_active,
    parse_ssid,
    parse_ssid_from_summary,
    parse_wifi_device,
)

APPLE_SILICON = """Hardware Port: Wi-Fi
Device: en0
Ethernet Address: a4:83:e7:11:22:33

Hardware Port: Thunderbolt Bridge
Device: bridge0
Ethernet Address: 36:7d:44:55:66:77
"""

INTEL_MAC = """Hardware Port: Ethernet
Device: en0
Ethernet Address: 00:11:22:33:44:55

Hardware Port: Wi-Fi
Device: en1
Ethernet Address: aa:bb:cc:dd:ee:ff
"""

NO_WIFI = """Hardware Port: Thunderbolt Bridge
Device: bridge0
Ethernet Address: 36:7d:44:55:66:77
"""


def test_finds_wifi_on_apple_silicon():
    assert parse_wifi_device(APPLE_SILICON) == "en0"


def test_finds_wifi_on_intel_where_it_is_not_en0():
    """The old hardcoded en0 picked Ethernet here and reported no network."""
    assert parse_wifi_device(INTEL_MAC) == "en1"


def test_returns_none_when_there_is_no_wifi_hardware():
    assert parse_wifi_device(NO_WIFI) is None


def test_handles_empty_output():
    assert parse_wifi_device("") is None


def test_reads_a_connected_network():
    assert parse_ssid("Current Wi-Fi Network: Haseeb 5GHz\n") == "Haseeb 5GHz"


def test_network_name_containing_a_colon_survives():
    assert parse_ssid("Current Wi-Fi Network: Cafe: Free WiFi\n") == "Cafe: Free WiFi"


def test_not_associated_is_not_read_as_a_verdict():
    """macOS 14+ says this to a process lacking Location Services, connected or not."""
    assert parse_ssid("You are not associated with an AirPort network.\n") is None


def test_blank_network_name_names_nothing():
    assert parse_ssid("Current Wi-Fi Network: \n") is None


def test_link_status_is_read_from_ifconfig():
    active = "en0: flags=8863<UP,BROADCAST,SMART,RUNNING>\n\tmedia: autoselect\n\tstatus: active\n"
    inactive = "en0: flags=8863<UP,BROADCAST,SMART>\n\tmedia: autoselect (<unknown type>)\n\tstatus: inactive\n"
    assert parse_link_active(active) is True
    assert parse_link_active(inactive) is False
    assert parse_link_active("") is False


def test_ipconfig_summary_fallback():
    summary = """<dictionary> {
  InterfaceType : WiFi
  SSID : Haseeb 5GHz
  Router : 192.168.1.1
}"""
    assert parse_ssid_from_summary(summary) == "Haseeb 5GHz"


def test_ipconfig_summary_without_an_ssid():
    assert parse_ssid_from_summary("<dictionary> {\n  Router : 192.168.1.1\n}") is None


def test_ipconfig_redacted_ssid_is_not_treated_as_a_name():
    assert parse_ssid_from_summary("  SSID : <redacted>") is None


# --- probe ordering: which source gets the last word ---

import pytest

from mcp_server import macos
from mcp_server.tools import system

PORTS = "Hardware Port: Wi-Fi\nDevice: en0\nEthernet Address: a4:83:e7:11:22:33\n"


def _fake_run(responses):
    """Reply to each command by its first two argv items."""

    async def run(*argv, **kwargs):
        for key, output in responses.items():
            if argv[:2] == key:
                return macos.Completed(0, output, "")
        return macos.Completed(1, "", "unexpected command")

    return run


async def test_interface_overrules_a_wrong_not_associated_verdict(monkeypatch):
    """networksetup can claim "not associated" while the interface holds an SSID."""
    monkeypatch.setattr(
        macos,
        "run",
        _fake_run(
            {
                ("networksetup", "-listallhardwareports"): PORTS,
                ("networksetup", "-getairportnetwork"): (
                    "You are not associated with an AirPort network.\n"
                ),
                ("ipconfig", "getsummary"): "  SSID : Haseeb 5GHz\n",
            }
        ),
    )
    assert await system._wifi() == ("Haseeb 5GHz", None)


async def test_connected_but_nameless_blames_permissions_not_the_network(monkeypatch):
    """The regression: connected over Wi-Fi, reported as "not connected".

    Every name source stays silent without Location Services, so only the link
    status can say whether we are actually online. It is active here.
    """
    monkeypatch.setattr(
        macos,
        "run",
        _fake_run(
            {
                ("networksetup", "-listallhardwareports"): PORTS,
                ("networksetup", "-getairportnetwork"): (
                    "You are not associated with an AirPort network.\n"
                ),
                ("ipconfig", "getsummary"): "<dictionary> {\n  Router : 10.0.0.1\n}",
                ("ifconfig", "en0"): "en0: flags=8863\n\tstatus: active\n",
            }
        ),
    )
    ssid, reason = await system._wifi()
    assert ssid is None
    assert reason == LOCATION_HINT
    assert "Not connected" not in reason


async def test_not_connected_only_when_the_link_is_down(monkeypatch):
    monkeypatch.setattr(
        macos,
        "run",
        _fake_run(
            {
                ("networksetup", "-listallhardwareports"): PORTS,
                ("networksetup", "-getairportnetwork"): (
                    "You are not associated with an AirPort network.\n"
                ),
                ("ipconfig", "getsummary"): "<dictionary> {\n}",
                ("ifconfig", "en0"): "en0: flags=8863\n\tstatus: inactive\n",
            }
        ),
    )
    ssid, reason = await system._wifi()
    assert ssid is None
    assert "Not connected" in reason


async def test_normal_connected_case_needs_only_networksetup(monkeypatch):
    monkeypatch.setattr(
        macos,
        "run",
        _fake_run(
            {
                ("networksetup", "-listallhardwareports"): PORTS,
                ("networksetup", "-getairportnetwork"): (
                    "Current Wi-Fi Network: Haseeb 5GHz\n"
                ),
            }
        ),
    )
    assert await system._wifi() == ("Haseeb 5GHz", None)


# --- boolean readings ---


def test_applescript_booleans():
    from mcp_server.tools.system import parse_boolean

    assert parse_boolean("true") is True
    assert parse_boolean(" FALSE \n") is False
    # Anything unexpected reads as unknown, not as False — an unreadable setting
    # and a setting that is off are different facts.
    assert parse_boolean("") is None
    assert parse_boolean("yes") is None
    assert parse_boolean("Not authorised") is None
