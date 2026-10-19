"""Telegram adapter: invite binding, long-poll handling and sends, against a fake Bot API (no network)."""
from tiwala_agent.negotiation import State
from tiwala_agent.telegram import Invites, Poller, TelegramSender, TgConfig, parse_update
from tiwala_agent.whatsapp import Gateway

from .test_negotiation import LUMEN, T0, cons, world  # noqa: F401  (world is a fixture)

CHAT = 555001234


class FakeBot:
    def __init__(self):
        self.sent, self.updates, self.next_id = [], [], 1

    def __call__(self, token, method, body, timeout=20):
        assert token == "T0KEN"
        if method == "sendMessage":
            self.sent.append(body)
            return {"message_id": len(self.sent)}
        if method == "getUpdates":
            out = [u for u in self.updates if u["update_id"] >= body["offset"]]
            return out
        if method == "getMe":
            return {"username": "TiwalaTestBot"}
        raise AssertionError(method)

    def msg(self, text, chat=CHAT, kind="private"):
        u = {"update_id": 100 + self.next_id, "message": {"message_id": self.next_id, "date": T0,
                                                         "chat": {"id": chat, "type": kind}, "text": text}}
        self.next_id += 1
        self.updates.append(u)
        return u


def setup(world, live=True):  # noqa: F811
    bot, eng = FakeBot(), world["eng"]
    cfg = TgConfig("T0KEN", live)
    esc = []
    g = Gateway(world["tmp"] / "wa", None, eng.supplier_text,
                lambda a: next((x.id for x in eng.store.all() if x.state not in ("rejected", "expired", "cancelled",
                                                                                  "escrow_created")), None),
                lambda nid, note: esc.append(note), lambda e, **k: None, clock=world["clock"],
                tg=TelegramSender(cfg, bot))
    p = Poller(g, cfg, world["tmp"] / "wa", lambda a: "Lumen Textiles", call=bot, clock=world["clock"])
    return bot, g, p, esc


def bind(bot, p):
    link = p.invite_link(LUMEN)
    assert link.startswith("https://t.me/TiwalaTestBot?start=")
    bot.msg(f"/start {link.split('start=')[1]}")
    p.run_once()
    return link


def test_invite_binds_chat_once_and_is_single_use(world):  # noqa: F811
    bot, g, p, _ = setup(world)
    link = bind(bot, p)
    c = g.contacts.get(LUMEN)
    assert c.channel == "telegram" and c.wa_id == f"tg:{CHAT}" and c.opted_in
    assert "Linked as Lumen Textiles" in bot.sent[-1]["text"]
    bot.msg(f"/start {link.split('start=')[1]}", chat=999)  # someone else reuses the link
    p.run_once()
    assert g.contacts.get(LUMEN).wa_id == f"tg:{CHAT}" and "not valid" in bot.sent[-1]["text"]


def test_codes_are_hashed_and_expire(world):  # noqa: F811
    inv = Invites(world["tmp"], world["clock"])
    code = inv.create(LUMEN, ttl_s=60)
    assert code not in (world["tmp"] / "telegram_invites.json").read_text()
    world["clock"].t += 61
    assert inv.redeem(code) is None


def test_unknown_chat_is_ignored_and_groups_are_dropped(world):  # noqa: F811
    bot, g, p, _ = setup(world)
    bot.msg("ACCEPT 123456", chat=777)
    bot.msg("hello", chat=-100, kind="group")
    p.run_once()
    assert bot.sent == [] and g.contacts.get(LUMEN) is None
    assert parse_update({"edited_message": {"text": "x"}}) is None


def test_offer_reply_and_accept_over_telegram(world):  # noqa: F811
    bot, g, p, _ = setup(world)
    bind(bot, p)
    n = world["eng"].open("0xWALLET", "Lumen Textiles", LUMEN, "Cotton fabric", cons(), "whatsapp", "telegram",
                          f"tg:{CHAT}", "none")
    rec = g.send(n.id, LUMEN, f"Offer: reply ACCEPT {n.current().code}")
    assert rec["status"] == "sent" and bot.sent[-1]["chat_id"] == CHAT and rec["to"] == "tg:••••1234"
    bot.msg(f"ACCEPT {n.current().code}")
    p.run_once()
    p.run_once()  # offset advanced: the same update is not handled twice
    n = world["eng"].store.get(n.id)
    assert n.state == State.AWAITING_BUYER_APPROVAL.value and n.agreement


def test_stop_opts_out_and_sending_is_gated(world):  # noqa: F811
    bot, g, p, esc = setup(world)
    bind(bot, p)
    n = world["eng"].open("0xWALLET", "Lumen Textiles", LUMEN, "Cotton fabric", cons(), "whatsapp", "telegram",
                          f"tg:{CHAT}", "none")
    bot.msg("/stop")
    p.run_once()
    assert not g.contacts.get(LUMEN).opted_in and any("opted out" in e for e in esc)
    assert g.send(n.id, LUMEN, "hello")["status"] == "blocked"
    bot2, g2, p2, _ = setup(world, live=False)
    assert TelegramSender(TgConfig("T0KEN", False), bot2).send(f"tg:{CHAT}", "x")[0] is False and bot2.sent == []


def test_token_never_appears_in_errors(world):  # noqa: F811
    def boom(token, method, body, timeout=20):
        raise RuntimeError(f"failed https://api.telegram.org/bot{token}/sendMessage")
    ok, _, err = TelegramSender(TgConfig("T0KEN", True), boom).send(f"tg:{CHAT}", "x")
    assert not ok and "T0KEN" not in err and "<token>" in err
