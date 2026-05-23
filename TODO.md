# TODO

Things we want to do later but aren't doing now. New entries land at the
top; mark items `[x]` when shipped (or strike through) rather than
deleting, so we keep the audit trail.

## Open

### Discord: reply vs. message

The Discord source currently sends every response via `channel.send(...)`,
which means responses appear as standalone messages. Discord also has a
true *reply* primitive — `message.reply(...)` / `channel.send(reference=...)`
— which renders the reply with a small "↩" pointing at the message it's
answering.

Decide which mode to use, and when:

- **Always reply** (every bot response uses `message.reply()`): users
  always see the back-pointer; channels stay tidy; but every reply
  visually breaks the channel rhythm and looks "noisy" for non-targeted
  responses (like greetings or url-grab titles).
- **Reply only when the user addressed us directly** (mention, prefix,
  command). Use `channel.send()` for passive responses (chatter
  greetings, url-grab, memo delivery, reminders).
- **Reply only when the response is uniquely tied to one user's
  message** (commands, factoid lookups). Use `channel.send()` for
  broadcast/ambient stuff.

The third one is probably right but needs the `Event` to know whether
the source supports replies and to carry the original message id. That
means:

- Extend `Source.send_message(...)` to accept an optional
  `reply_to: str | None` parameter (opaque message id, source-specific).
- Track the underlying message id on the `Event` (Discord: `message.id`;
  IRC: unused).
- Decide per-handler whether to thread that through, or make `event.reply()`
  pass it automatically when the handler is a `@command` (which is
  inherently a direct response).

IRC has no equivalent so it just ignores `reply_to`.

## Done
