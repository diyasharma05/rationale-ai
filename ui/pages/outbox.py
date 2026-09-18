"""Outbox: drafted messages waiting on a human, and what has been sent.

The last mile of intelligence-to-action. Every message here was routed by the
semantic contract, not by the model, and none of them leave until someone
approves them.
"""
import pandas as pd
import streamlit as st

from services import outbox, transports
from ui.common import C, section_label, stat_tile

_STATUS_COLOR = {
    "draft": "warning", "approved": "series", "sent": "good",
    "failed": "critical", "cancelled": "ink2",
}


def render(ctx):
    actor = ctx.viewer.role_id

    st.header("Outbox")
    st.caption("Recommended actions become messages to the person the **contract** "
               "names as their owner, with the approval the contract requires. "
               "The model writes the sentence; it does not choose the recipient.")

    transport = transports.get_transport()
    if transport.live:
        st.warning(f"Live delivery is ON via **{transport.name}**. Approved messages "
                   "will actually be sent.")
    else:
        st.info("**Dry run.** Approved messages are recorded, not delivered. Set "
                "`RATIONALE_DISPATCH=mcp` and `RATIONALE_MCP_COMMAND` to deliver "
                "through any MCP server — the adapter discovers the server's posting "
                "tool and maps arguments from its schema, and is tested end-to-end "
                "against a real MCP server. Delivery is opt-in on purpose: an engine "
                "that can message people is a different risk class from one that "
                "draws a page.")

    msgs = outbox.messages()
    counts = outbox.summary()
    cols = st.columns(4)
    for col, key, label in zip(cols, ("draft", "approved", "sent", "failed"),
                               ("Awaiting approval", "Approved", "Sent", "Failed")):
        col.markdown(stat_tile(label, str(counts.get(key, 0)),
                               accent=C[_STATUS_COLOR[key]]), unsafe_allow_html=True)

    if not msgs:
        st.info("Nothing queued. Run an investigation that reaches a conclusion and "
                "use **Draft dispatch** to route its actions. Investigations that "
                "find no signal, or that are too new to diagnose, deliberately "
                "produce nothing to send.")
        return

    pending = [m for m in msgs if m["status"] == "draft"]
    if pending:
        section_label("Waiting on you")
    for m in pending:
        unrouted = m["to"] == "—"
        with st.container(border=True):
            head = f"**{m['subject']}**"
            st.markdown(head)
            st.caption(f"to **{m['to']}**"
                       + (f"  ·  approval: **{m['cc']}**" if m["cc"] else "")
                       + f"  ·  {m['kind'].replace('_', ' ')}  ·  confidence "
                       f"{m['confidence']:.0%}")
            if unrouted:
                st.warning("No owner for this lever in the contract, so there is "
                           "nobody to send it to. That is a gap in the contract "
                           "worth fixing, not a message to guess a recipient for.")
            st.text(m["body"])
            note = st.text_input("Approval note (recorded in the audit trail)",
                                 key=f"note_{m['id']}")
            a1, a2, _ = st.columns([1, 1, 3])
            if a1.button("Approve & send", key=f"ok_{m['id']}", type="primary",
                         disabled=unrouted):
                outbox.approve(m["id"], actor=actor, note=note)
                res = outbox.send(m["id"])
                if res.get("ok"):
                    st.toast(f"Sent via {res.get('transport')}", icon="✅")
                else:
                    st.error(f"Not sent: {res.get('detail')}")
                ctx.nav.refresh()
            if a2.button("Discard", key=f"no_{m['id']}"):
                outbox.cancel(m["id"], actor=actor, reason=note)
                ctx.nav.refresh()

    handled = [m for m in msgs if m["status"] != "draft"]
    if handled:
        section_label("Already actioned")
        st.dataframe(pd.DataFrame([{
            "id": m["id"], "status": m["status"], "to": m["to"],
            "kpi": m["kpi_name"], "period": m["period"],
            "approved by": m.get("approved_by", "—"),
            "via": m.get("sent_via", "—"),
            "subject": m["subject"],
        } for m in handled])[::-1], hide_index=True, width="stretch")
        st.caption("Draft, approval and send are logged as separate events, so "
                   "'who approved this, and when' stays answerable afterwards.")
