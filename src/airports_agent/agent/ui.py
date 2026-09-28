"""
Streamlit reruns the whole script on every interaction, and there's no clean hook to keep a
single long-lived async connection open across reruns. So each user turn opens a fresh
AirportsAgent (a new MCP subprocess + Gemini chat) rather than persisting one connection for the
whole browser session - simpler and more robust than fighting Streamlit's rerun model, at the
cost of a small per-turn connection overhead. Multi-turn context is kept anyway by round-tripping
Gemini's own chat history through st.session_state.
"""

import asyncio
from typing import Any, Dict, List, Tuple

import streamlit as st
from google.genai import types

from airports_agent.agent.agent import NO_ANSWER_MESSAGE, AirportsAgent

st.set_page_config(page_title="Airports Investment Agent", page_icon=":airplane:")
st.title(":airplane: Airports Investment Agent")
st.caption(
    "Ask about airport congestion, capacity, and long-haul traffic to help identify "
    "modernization/investment candidates. Answers are grounded in live flight data - "
    "expand \"Tool calls\" under an answer to see exactly what was queried."
)

if "gemini_history" not in st.session_state:
    st.session_state.gemini_history: List[types.Content] = []
if "messages" not in st.session_state:
    st.session_state.messages: List[Dict[str, Any]] = []


async def _ask(
    user_message: str, history: List[types.Content]
) -> Tuple[str, List[types.Content], List[Dict[str, Any]]]:
    async with AirportsAgent(history=history) as agent:
        answer = await agent.ask(user_message)
        return answer or NO_ANSWER_MESSAGE, agent.chat.get_history(), agent.last_tool_calls


def _render_tool_calls(tool_calls: List[Dict[str, Any]]) -> None:
    if not tool_calls:
        return
    with st.expander(f"Tool calls ({len(tool_calls)})"):
        for call in tool_calls:
            st.markdown(f"**{call['name']}**({call['args']})")
            st.json(call["result"])


for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["text"])
        _render_tool_calls(message.get("tool_calls", []))

if user_message := st.chat_input("e.g. Which New England airports are strong expansion candidates?"):
    st.session_state.messages.append({"role": "user", "text": user_message})
    with st.chat_message("user"):
        st.markdown(user_message)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                text, new_history, tool_calls = asyncio.run(
                    _ask(user_message, st.session_state.gemini_history)
                )
            except Exception as e:
                print(f"[ui] Agent turn failed: {e}")
                text, tool_calls = f"Something went wrong: {e}", []
                new_history = st.session_state.gemini_history
        st.markdown(text)
        _render_tool_calls(tool_calls)

    st.session_state.gemini_history = new_history
    st.session_state.messages.append({"role": "assistant", "text": text, "tool_calls": tool_calls})
