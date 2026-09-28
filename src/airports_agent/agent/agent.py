import asyncio
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import Tool as McpTool

from airports_agent.agent.system_prompt import SYSTEM_PROMPT
from airports_agent.settings.settings import load_settings

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[3]


RETRYABLE_STATUS_CODES = {429, 503}
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2


def _mcp_tools_to_gemini_tool(mcp_tools: List[McpTool]) -> types.Tool:
    """Converts MCP tool declarations to a Gemini Tool"""
    return types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters_json_schema=tool.inputSchema,
            )
            for tool in mcp_tools
        ]
    )


class AirportsAgent:
    """Async context manager: launches the airports MCP server as a stdio subprocess and holds a
    Gemini chat session. Tool calls Gemini requests are executed against the live MCP session and
    fed back manually (see _mcp_tools_to_gemini_tool for why).

    Usage:
        async with AirportsAgent() as agent:
            response = await agent.ask("What's the congestion level at KBOS?")
            print(response.text)
            print(agent.last_tool_calls)  # [{"name": ..., "args": ..., "result": ...}, ...]
    """

    def __init__(self):
        settings = load_settings()
        self._client = genai.Client()
        self._model = settings.llm.model
        self._exit_stack = AsyncExitStack()
        self._session: ClientSession = None
        self.chat = None
        self.last_tool_calls: List[Dict[str, Any]] = []

    async def __aenter__(self) -> "AirportsAgent":
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "airports_agent.agent.mcp_server"],
            cwd=str(PROJECT_ROOT),
        )
        read, write = await self._exit_stack.enter_async_context(stdio_client(params))
        session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._session = session

        mcp_tools = (await session.list_tools()).tools
        self.chat = self._client.aio.chats.create(
            model=self._model,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=[_mcp_tools_to_gemini_tool(mcp_tools)],
            ),
        )
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._exit_stack.aclose()

    async def ask(self, message: str) -> types.GenerateContentResponse:
        """Sends a message in the ongoing chat, executing any tool calls Gemini requests against
        the MCP session and feeding the results back until it produces a final answer.
        `last_tool_calls` is reset and (re)populated with the calls made to answer this message.
        """
        self.last_tool_calls = []
        response = await self._send_message(message)

        while response.function_calls:
            response_parts = []
            for call in response.function_calls:
                args = call.args or {}
                print(f"[tool] {call.name}({args})")
                result = await self._session.call_tool(call.name, args)
                data = result.structuredContent if not result.isError else {
                    "error": self._result_text(result)
                }
                self.last_tool_calls.append({"name": call.name, "args": args, "result": data})
                response_parts.append(types.Part.from_function_response(name=call.name, response=data))
            response = await self._send_message(response_parts)

        return response

    async def _send_message(self, message) -> types.GenerateContentResponse:
        """Wraps chat.send_message with a short retry for transient Gemini API errors (503
        "high demand", 429 rate/quota limited)."""
        for attempt in range(MAX_RETRIES):
            try:
                return await self.chat.send_message(message)
            except genai_errors.APIError as e:
                if e.code not in RETRYABLE_STATUS_CODES or attempt == MAX_RETRIES - 1:
                    raise
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)

    @staticmethod
    def _result_text(result) -> str:
        return " ".join(block.text for block in result.content if hasattr(block, "text"))


async def _cli_chat() -> None:
    async with AirportsAgent() as agent:
        print("Airports agent ready (Ctrl+C to exit).")
        while True:
            try:
                user_input = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not user_input:
                continue
            try:
                response = await agent.ask(user_input)
            except genai_errors.APIError as e:
                print(f"\n[Gemini API error {e.code}: {e.message}. Try again in a moment.]")
                continue
            print(f"\nAgent: {response.text}")


if __name__ == "__main__":
    asyncio.run(_cli_chat())
