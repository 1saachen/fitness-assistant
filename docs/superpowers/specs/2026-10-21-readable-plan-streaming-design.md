# Readable plan streaming

The user approved readable content first, followed by structured plan extraction.
Long-term and daily planning gain opt-in POST SSE endpoints. Existing JSON endpoints
remain compatible. The UI streams plain text into a temporary draft panel and shows
the saved cards only after validation and persistence succeed. Errors retain the
preview with an explicit incomplete label, including existing needs-input and
snapshot conflict information. Preview text is rendered with textContent.

For each live planning agent, first generate a readable draft with no tools, using
the same role, task and safety constraints. Then include that exact draft in the
structured planning conversation. Both calls share the agent time and call budget;
usage includes the preview. The preview does not have persistence authority and
is labelled provisional because validation may revise it. Demo mode uses the same
event lifecycle without a model call. No model reasoning is exposed.

SSE transport preserves UTF-8 across byte boundaries, bounds upstream bytes and
timeouts, requires a completed upstream stream, sends keepalives downstream, and
uses a bounded worker queue and admits at most four active workers per process.
Excess requests receive a terminal capacity error (503). Disconnect stops further event delivery and aborts
at the next provider event or phase boundary; a write already in progress may
finish and can be recovered through planning history. No automatic POST retries.
