"""Parsing tests for the Wi-Fi probe.

The commands cannot run off macOS, but their output shapes are stable, so the
parsing is pinned here against real captures.
"""

from mcp_server.tools.system import (
    LOCATION_HINT,
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
    ssid, reason = parse_ssid("Current Wi-Fi Network: Haseeb 5GHz\n")
    assert ssid == "Haseeb 5GHz"
    assert reason is None


def test_network_name_containing_a_colon_survives():
    ssid, _ = parse_ssid("Current Wi-Fi Network: Cafe: Free WiFi\n")
    assert ssid == "Cafe: Free WiFi"


def test_reports_not_connected_rather_than_a_bare_null():
    ssid, reason = parse_ssid(
        "You are not associated with an AirPort network.\n"
    )
    assert ssid is None
    assert "Not connected" in reason


def test_blank_network_name_reads_as_a_permissions_problem():
    ssid, reason = parse_ssid("Current Wi-Fi Network: \n")
    assert ssid is None
    assert reason == LOCATION_HINT


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


async def test_not_connected_stands_when_both_sources_agree(monkeypatch):
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
