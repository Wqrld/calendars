"""Tests for ICalendarParser and email template rendering."""

# pylint: disable=missing-function-docstring,protected-access

import re
from unittest.mock import MagicMock, patch

from django.template.loader import render_to_string

import pytest

from core.services.calendar_invitation_service import (
    CalendarInvitationService,
    ICalendarParser,
)

# Sample ICS with URL property
ICS_WITH_URL = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:test-123
DTSTART:20260210T140000Z
DTEND:20260210T150000Z
SUMMARY:Réunion d'équipe
DESCRIPTION:Point hebdomadaire
LOCATION:Salle 301
URL:https://visio.numerique.gouv.fr/abc-defg-hij
ORGANIZER;CN=Alice:mailto:alice@example.com
ATTENDEE;CN=Bob;RSVP=TRUE:mailto:bob@example.com
SEQUENCE:0
END:VEVENT
END:VCALENDAR"""

# Sample ICS without URL property
ICS_WITHOUT_URL = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:test-456
DTSTART:20260210T140000Z
DTEND:20260210T150000Z
SUMMARY:Simple meeting
ORGANIZER;CN=Alice:mailto:alice@example.com
ATTENDEE;CN=Bob;RSVP=TRUE:mailto:bob@example.com
SEQUENCE:0
END:VEVENT
END:VCALENDAR"""


class TestICalendarParserUrl:
    """Tests for URL property extraction in ICalendarParser."""

    def test_parse_extracts_url_when_present(self):
        event = ICalendarParser.parse(ICS_WITH_URL, "bob@example.com")
        assert event is not None
        assert event.url == "https://visio.numerique.gouv.fr/abc-defg-hij"

    def test_parse_url_is_none_when_absent(self):
        event = ICalendarParser.parse(ICS_WITHOUT_URL, "bob@example.com")
        assert event is not None
        assert event.url is None

    def test_parse_preserves_other_fields_with_url(self):
        event = ICalendarParser.parse(ICS_WITH_URL, "bob@example.com")
        assert event is not None
        assert event.summary == "Réunion d'équipe"
        assert event.description == "Point hebdomadaire"
        assert event.location == "Salle 301"
        assert event.organizer_email == "alice@example.com"


class TestSanitizeUrl:
    """The ICS URL property is rendered straight into invitation emails
    as <a href=...>. An attacker who can put an event on a victim's
    calendar (by definition, what an invitation does) could otherwise
    smuggle ``javascript:``, ``data:`` or scheme-less values through to
    the recipient's mail client. Hard-allowlist the schemes we render."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("https://meet.example.com/abc", "https://meet.example.com/abc"),
            ("http://meet.example.com/abc", "http://meet.example.com/abc"),
            ("mailto:host@example.com", "mailto:host@example.com"),
            ("tel:+33123456789", "tel:+33123456789"),
            ("  https://meet.example.com/abc  ", "https://meet.example.com/abc"),
            ("HTTPS://meet.example.com/abc", "HTTPS://meet.example.com/abc"),
        ],
    )
    def test_safe_schemes_pass_through(self, raw, expected):
        assert ICalendarParser.sanitize_url(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "javascript:alert(document.cookie)",
            "JAVASCRIPT:alert(1)",
            "  javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "vbscript:msgbox(1)",
            "file:///etc/passwd",
            "//evil.example.com/path",  # protocol-relative
            "/relative/path",
            "relative-path",
            "",
            None,
        ],
    )
    def test_unsafe_schemes_are_dropped(self, raw):
        assert ICalendarParser.sanitize_url(raw) is None

    def test_javascript_url_does_not_reach_template(self):
        ics = (
            "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Test//EN\n"
            "BEGIN:VEVENT\nUID:xss-1\n"
            "DTSTART:20260210T140000Z\nDTEND:20260210T150000Z\n"
            "SUMMARY:Click me\n"
            "URL:javascript:alert(document.cookie)\n"
            "ORGANIZER;CN=Mallory:mailto:mallory@evil.com\n"
            "ATTENDEE;CN=Bob;RSVP=TRUE:mailto:bob@example.com\n"
            "SEQUENCE:0\nEND:VEVENT\nEND:VCALENDAR"
        )
        event = ICalendarParser.parse(ics, "bob@example.com")
        assert event is not None
        assert event.url is None


class TestICalendarParserLineInjection:
    """Pin the parser's resistance to ICS field smuggling.

    These tests exist because ``ICalendarParser`` was historically a
    hand-rolled regex parser whose safety depended on every byte having
    been re-serialized by sabre/vobject upstream — a fragile invariant.
    The parser is now backed by the ``icalendar`` library, but the
    contract these tests pin (no field-smuggling, no header injection,
    no nested-block confusion) must hold regardless of which parser
    backs ``ICalendarParser``. If you swap the implementation, these
    tests must keep passing.

    Each payload represents a thing an attacker could try to put in
    an ICS field — usually inside DESCRIPTION or SUMMARY — to cause a
    different field to take a value the attacker chose.
    """

    @staticmethod
    def _wrap(vevent_body: str) -> str:
        """Wrap a VEVENT body in a minimal valid VCALENDAR."""
        return (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:line-injection-test\r\n"
            "DTSTART:20260210T140000Z\r\n"
            "DTEND:20260210T150000Z\r\n"
            f"{vevent_body}\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )

    def test_description_with_escaped_newline_does_not_split_into_attendee(self):
        """RFC 5545 ``\\n`` inside DESCRIPTION is a logical newline of
        the *value*, not a property delimiter. The parser must not
        treat the post-``\\n`` text as a new ATTENDEE property."""
        ics = self._wrap(
            "DESCRIPTION:Hi there.\\nATTENDEE;CN=Mallory:mailto:victim@target.com\r\n"
            "ORGANIZER;CN=Real:mailto:real@example.com\r\n"
            "ATTENDEE;CN=Bob:mailto:bob@example.com"
        )
        event = ICalendarParser.parse(ics, "bob@example.com")
        assert event is not None
        # The ONLY attendee the parser reports for the recipient must be the real one.
        assert event.attendee_email == "bob@example.com"
        # The smuggled CN must NOT be picked up.
        assert event.attendee_name != "Mallory"
        # The DESCRIPTION must contain the literal newline-escaped value.
        assert event.description is not None
        assert (
            "ATTENDEE" in event.description
        )  # the attacker's bytes are still IN the description
        # …but they did not become a property.
        assert event.organizer_email == "real@example.com"

    @pytest.mark.parametrize("itip_enabled", [True, False])
    def test_summary_with_embedded_method_is_not_treated_as_calendar_method(
        self, itip_enabled, settings
    ):
        """A METHOD-looking substring inside SUMMARY must not result in
        a top-of-line ``METHOD:CANCEL`` property on the outgoing
        attachment, in either ITIP mode."""
        settings.CALENDAR_ITIP_ENABLED = itip_enabled

        ics = self._wrap(
            "SUMMARY:Important: METHOD:CANCEL was discussed\r\n"
            "ORGANIZER;CN=Real:mailto:real@example.com\r\n"
            "ATTENDEE;CN=Bob:mailto:bob@example.com"
        )
        event = ICalendarParser.parse(ics, "bob@example.com")
        assert event is not None
        assert "METHOD:CANCEL" in event.summary

        service = CalendarInvitationService()
        rewritten = service._prepare_ics_attachment(ics, "REQUEST")

        # No bare ``METHOD:CANCEL`` line at start-of-line in the output,
        # regardless of whether ITIP is enabled or not. (The substring
        # "METHOD:CANCEL" *can* still appear inside the SUMMARY value;
        # what matters is that no top-level METHOD property got smuggled.)
        bare_cancel = re.search(r"(?:^|\r?\n)METHOD:CANCEL\b", rewritten)
        assert bare_cancel is None, (
            f"Smuggled METHOD:CANCEL appeared as a top-level property "
            f"in the rewritten ICS (itip_enabled={itip_enabled}):\n{rewritten}"
        )

    def test_organizer_cn_with_crlf_does_not_inject_email_header(self):
        """CRLF in ORGANIZER CN parameter must not become an email header
        line. Validated end-to-end via Django's BadHeaderError if needed,
        but the parser-level guarantee is: the parsed ``organizer_name``
        contains no CR/LF."""
        ics = self._wrap(
            'ORGANIZER;CN="Real\\r\\nBcc: secret@target.com":mailto:real@example.com\r\n'
            "SUMMARY:Test\r\n"
            "ATTENDEE;CN=Bob:mailto:bob@example.com"
        )
        event = ICalendarParser.parse(ics, "bob@example.com")
        assert event is not None
        # icalendar lib unescapes \r\n inside text values; if the CN somehow
        # contained literal CR/LF after parsing, that would be a smuggling
        # primitive. Assert no CR/LF made it through.
        if event.organizer_name:
            assert "\r" not in event.organizer_name
            assert "\n" not in event.organizer_name

    def test_nested_vevent_in_description_not_picked_up_as_outer_event(self):
        """A non-greedy regex parser would have matched the inner block
        if a literal ``BEGIN:VEVENT...END:VEVENT`` appeared inside a
        DESCRIPTION. The icalendar lib correctly parses only one level
        — assert the OUTER UID/SUMMARY win."""
        # Use \\n (escaped newline within DESCRIPTION value) to put
        # BEGIN:VEVENT-looking text inside DESCRIPTION; per RFC 5545
        # this is text content of the outer DESCRIPTION property.
        ics = self._wrap(
            "SUMMARY:Real Outer Event\r\n"
            "DESCRIPTION:Notes:\\nBEGIN:VEVENT\\nUID:fake-inner\\n"
            "SUMMARY:Fake Inner\\nEND:VEVENT\r\n"
            "ORGANIZER;CN=Real:mailto:real@example.com\r\n"
            "ATTENDEE;CN=Bob:mailto:bob@example.com"
        )
        event = ICalendarParser.parse(ics, "bob@example.com")
        assert event is not None
        # The outer UID is from the wrapper; we hardcode it to "line-injection-test".
        assert event.uid == "line-injection-test"
        assert event.summary == "Real Outer Event"
        assert event.organizer_email == "real@example.com"

    def test_multiple_attendees_match_only_recipient(self):
        """When the recipient happens to be a substring of another
        attendee's email, the parser must match the EXACT email — not
        a prefix or suffix."""
        ics = self._wrap(
            "SUMMARY:Test\r\n"
            "ORGANIZER:mailto:org@example.com\r\n"
            "ATTENDEE;CN=Evil:mailto:bob@example.com.evil.tld\r\n"
            "ATTENDEE;CN=Real Bob:mailto:bob@example.com\r\n"
            "ATTENDEE;CN=Other:mailto:notbob@example.com"
        )
        event = ICalendarParser.parse(ics, "bob@example.com")
        assert event is not None
        # Should match only the real Bob — not the evil substring match.
        assert event.attendee_email == "bob@example.com"
        assert event.attendee_name == "Real Bob"

    def test_url_property_with_carriage_return_in_value_does_not_split(self):
        """A URL containing escaped CR (``\\r``) must not split into a
        new property line."""
        ics = self._wrap(
            "SUMMARY:Test\r\n"
            "URL:https://example.com/path\\rATTENDEE:mailto:victim@target.com\r\n"
            "ORGANIZER:mailto:real@example.com\r\n"
            "ATTENDEE;CN=Bob:mailto:bob@example.com"
        )
        event = ICalendarParser.parse(ics, "bob@example.com")
        assert event is not None
        # URL must either be the (sanitized) full string or None — but
        # there must be exactly one ATTENDEE-derived recipient, the real Bob.
        assert event.attendee_email == "bob@example.com"
        # ORGANIZER must be the real one, not the smuggled one.
        assert event.organizer_email == "real@example.com"

    def test_payload_without_vevent_returns_none(self):
        """An ICS with VTIMEZONE but no VEVENT must NOT pick up
        DTSTART/DTEND from the timezone block (the historical regex
        parser was vulnerable to this — VTIMEZONE has 1970 dates for
        DST rules and would mark an event as 'past')."""
        ics = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\n"
            "BEGIN:VTIMEZONE\r\nTZID:Europe/Paris\r\n"
            "BEGIN:STANDARD\r\nDTSTART:19701025T030000\r\n"
            "TZOFFSETFROM:+0200\r\nTZOFFSETTO:+0100\r\nEND:STANDARD\r\n"
            "END:VTIMEZONE\r\nEND:VCALENDAR\r\n"
        )
        event = ICalendarParser.parse(ics, "bob@example.com")
        assert event is None

    def test_is_event_past_does_not_pick_up_vtimezone_dtstart(self):
        """``is_event_past`` must read DTSTART from VEVENT only —
        VTIMEZONE blocks contain DTSTART for DST rules dated to 1970
        which would otherwise mark every event as past."""
        future = "20990101T120000Z"
        ics = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\n"
            "BEGIN:VTIMEZONE\r\nTZID:Europe/Paris\r\n"
            "BEGIN:STANDARD\r\nDTSTART:19701025T030000\r\n"
            "TZOFFSETFROM:+0200\r\nTZOFFSETTO:+0100\r\nEND:STANDARD\r\n"
            "END:VTIMEZONE\r\n"
            "BEGIN:VEVENT\r\nUID:future\r\n"
            f"DTSTART:{future}\r\nDTEND:{future}\r\n"
            "SUMMARY:Far future\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        assert ICalendarParser.is_event_past(ics) is False


@pytest.mark.django_db
class TestEmailTemplateVisioUrl:
    """Tests for visio URL rendering in email templates."""

    def _build_context(self, event):
        service = CalendarInvitationService()
        return service._build_template_context(event, "REQUEST")

    def test_invitation_html_contains_visio_link(self):
        event = ICalendarParser.parse(ICS_WITH_URL, "bob@example.com")
        context = self._build_context(event)
        html = render_to_string("emails/calendar_invitation.html", context)
        assert "https://visio.numerique.gouv.fr/abc-defg-hij" in html
        assert "Visio" in html

    def test_invitation_txt_contains_visio_link(self):
        event = ICalendarParser.parse(ICS_WITH_URL, "bob@example.com")
        context = self._build_context(event)
        txt = render_to_string("emails/calendar_invitation.txt", context)
        assert "https://visio.numerique.gouv.fr/abc-defg-hij" in txt
        assert "Visio" in txt

    def test_invitation_html_no_visio_when_absent(self):
        event = ICalendarParser.parse(ICS_WITHOUT_URL, "bob@example.com")
        context = self._build_context(event)
        html = render_to_string("emails/calendar_invitation.html", context)
        assert "Visio" not in html

    def test_invitation_txt_no_visio_when_absent(self):
        event = ICalendarParser.parse(ICS_WITHOUT_URL, "bob@example.com")
        context = self._build_context(event)
        txt = render_to_string("emails/calendar_invitation.txt", context)
        assert "Visio" not in txt


# ICS template for mailbox invitation tests
ICS_MAILBOX_INVITE = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:mailbox-invite-test-1
DTSTART:20260310T100000Z
DTEND:20260310T110000Z
SUMMARY:Mailbox Team Meeting
ORGANIZER;CN=Team Mailbox:mailto:team@company.com
ATTENDEE;CN=External;RSVP=TRUE:mailto:external@other.com
SEQUENCE:0
END:VEVENT
END:VCALENDAR"""


@pytest.mark.django_db
class TestMailboxInvitationRouting:
    """When is_mailbox=True, invitations MUST be sent through the
    Messages API (so the email comes from the mailbox address).
    Falling back to SMTP would send from the system address — the
    exact production bug this test guards against.
    """

    @pytest.fixture()
    def service(self):
        return CalendarInvitationService()

    @pytest.fixture()
    def _messages_settings(self, settings):
        settings.FEATURE_MESSAGES_INTEGRATION = True
        settings.MESSAGES_API_URL = "https://messages.test"
        settings.MESSAGES_API_KEY = "test-key"
        settings.MESSAGES_CHANNEL_ID = "test-channel"

    @pytest.mark.usefixtures("_messages_settings")
    def test_mailbox_invitation_routes_via_messages_api(self, service):
        """send_invitation(is_mailbox=True) must call _send_via_messages,
        NOT _send_email. If the email is sent via SMTP the 'from' address
        will be the system address instead of the mailbox identity."""
        mock_messages = MagicMock()
        mock_messages.get_mailbox_by_email.return_value = {
            "id": "mbx-123",
            "email": "team@company.com",
        }
        mock_messages.submit_raw_email.return_value = True

        with (
            patch(
                "core.services.calendar_invitation_service"
                ".CalendarInvitationService._send_email",
            ) as mock_send_email,
            patch(
                "core.services.messages_service.MessagesService.__init__",
                return_value=None,
            ),
            patch(
                "core.services.messages_service.MessagesService.get_mailbox_by_email",
                mock_messages.get_mailbox_by_email,
            ),
            patch(
                "core.services.messages_service.MessagesService.submit_raw_email",
                mock_messages.submit_raw_email,
            ),
        ):
            result = service.send_invitation(
                sender_email="team@company.com",
                recipient_email="external@other.com",
                method="REQUEST",
                icalendar_data=ICS_MAILBOX_INVITE,
                is_mailbox=True,
            )

        assert result is True, "Invitation should succeed via Messages API"
        mock_messages.get_mailbox_by_email.assert_called_once_with("team@company.com")
        mock_messages.submit_raw_email.assert_called_once()
        mock_send_email.assert_not_called()

    @pytest.mark.usefixtures("_messages_settings")
    def test_non_mailbox_invitation_routes_via_smtp(self, service):
        """send_invitation(is_mailbox=False) must call _send_email,
        NOT _send_via_messages."""
        with (
            patch(
                "core.services.calendar_invitation_service"
                ".CalendarInvitationService._send_email",
                return_value=True,
            ) as mock_send_email,
            patch(
                "core.services.calendar_invitation_service"
                ".CalendarInvitationService._send_via_messages",
            ) as mock_send_messages,
        ):
            result = service.send_invitation(
                sender_email="alice@example.com",
                recipient_email="bob@example.com",
                method="REQUEST",
                icalendar_data=ICS_WITH_URL,
                is_mailbox=False,
            )

        assert result is True
        mock_send_email.assert_called_once()
        mock_send_messages.assert_not_called()

    @pytest.mark.usefixtures("_messages_settings")
    def test_mailbox_invitation_no_smtp_fallback_on_messages_failure(self, service):
        """If _send_via_messages fails, the invitation must NOT fall
        back to SMTP. Sending a mailbox invitation from the system
        address is worse than not sending it at all — it confuses
        recipients and bypasses the mailbox identity."""
        with (
            patch(
                "core.services.calendar_invitation_service"
                ".CalendarInvitationService._send_email",
            ) as mock_send_email,
            patch(
                "core.services.calendar_invitation_service"
                ".CalendarInvitationService._send_via_messages",
                return_value=False,
            ),
        ):
            result = service.send_invitation(
                sender_email="team@company.com",
                recipient_email="external@other.com",
                method="REQUEST",
                icalendar_data=ICS_MAILBOX_INVITE,
                is_mailbox=True,
            )

        assert result is False, "Invitation should fail when Messages API fails"
        mock_send_email.assert_not_called()
