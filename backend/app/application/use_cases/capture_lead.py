from __future__ import annotations

from dataclasses import dataclass

from application.dto.leads import CaptureLeadCmd
from application.exceptions import payload_validation
from application.ports.email import EmailSender
from application.ports.magic_link import MagicLinkGenerator
from application.ports.rate import RateLimiter, RateLimitScope
from application.ports.repos import LeadsRepo
from application.ports.uow import UnitOfWork
from config.config import Settings
from domain.entities.lead import Lead
from domain.value_objects.email import Email
from domain.value_objects.ip_hash import IpHash
from domain.value_objects.lead_flow import LeadFlow


@dataclass
class CaptureLeadUseCase:
    """Capture an email, (re)issue a magic link, and deliver it (spec §9.2; honeypot §10.7)."""

    rate: RateLimiter
    leads_repo: LeadsRepo
    email_sender: EmailSender
    magic_link_gen: MagicLinkGenerator
    uow: UnitOfWork
    settings: Settings

    def execute(self, cmd: CaptureLeadCmd) -> None:
        """Silent-upsert the lead with a fresh magic link and email it inside one transaction.

        Email delivery runs inside the UoW: a Resend failure rolls the transaction back, leaving
        any prior magic link valid (§9.2). A non-empty honeypot is silently dropped before any
        side effect: the caller receives the regular ack while no Lead is created and no email
        is sent (§10.7).

        Args:
            cmd: The capture command (email, flow, ip hash, user-agent, honeypot).

        :raises InvalidPayloadError: email/flow primitive invalid (§9.0).
        :raises RateLimitExceededError: per-ip cap exceeded (§9.8).
        :raises UpstreamEmailError: the email provider call failed (§9.2 / §9.8).
        """
        if cmd.honeypot:
            # Antibot honeypot (§10.7): drop silently before any side effect — the bare
            # return becomes the regular 200 {"status":"sent"} ack in the interface layer,
            # indistinguishable from success (no Lead, no email, no rate hit).
            return
        with self.uow.transaction():
            self.rate.check_and_increment(RateLimitScope.IP, cmd.ip_hash)
        with payload_validation():
            email = Email(cmd.email)
            flow = LeadFlow(cmd.flow)
        # ip_hash is server-derived (sha256(ip||salt)); a bad value is our bug → 500, not a 422,
        # so it is built outside payload_validation (which converts client-payload errors).
        ip_hash = IpHash(cmd.ip_hash)
        new_magic_link = self.magic_link_gen.generate()
        with self.uow.transaction():
            existing = self.leads_repo.get_by_email_for_update(email)
            if existing is None:
                lead = Lead.create(
                    email=email,
                    magic_link=new_magic_link,
                    flow=flow,
                    ip_hash=ip_hash,
                    ua_short=cmd.ua_short,
                )
                self.leads_repo.add(lead)
            else:
                existing.regenerate_magic_link(new_magic_link)
                self.leads_repo.update(existing)
            self.email_sender.send_magic_link(to=email, magic_link=new_magic_link)
