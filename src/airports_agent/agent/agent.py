import asyncio
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Dict, List, Optional

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
NO_ANSWER_MESSAGE = "(No answer - the model call failed. Please try again in a moment.)"


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

    def __init__(self, history: Optional[List[types.Content]] = None):
        settings = load_settings()
        self._client = genai.Client()
        self._model = settings.llm.model
        self._exit_stack = AsyncExitStack()
        self._session: Optional[ClientSession] = None
        self._history = history
        self._config: Optional[types.GenerateContentConfig] = None
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
        self._config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[_mcp_tools_to_gemini_tool(mcp_tools)],
        )
        self._create_chat(self._history)
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._exit_stack.aclose()

    async def ask(self, message: str) -> str:
        self.last_tool_calls = []
        history_before = list(self.chat.get_history())
        response = await self._send_message(message)

        while response is not None and response.function_calls:
            response_parts = []
            for call in response.function_calls:
                args = call.args or {}
                print(f"[tool] {call.name}({args})")
                data = await self._call_tool(call.name, args)
                self.last_tool_calls.append({"name": call.name, "args": args, "result": data})
                response_parts.append(types.Part.from_function_response(name=call.name, response=data))
            response = await self._send_message(response_parts)

        if response is None:
            self._create_chat(history_before)
            return ""
        return response.text or ""

    def _create_chat(self, history: Optional[List[types.Content]]) -> None:
        self.chat = self._client.aio.chats.create(model=self._model, config=self._config, history=history)

    async def _call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Runs one tool on the MCP server. A tool that raised comes back as {"error": ...}; a
        failed call to the server itself is printed and returned as empty data."""
        try:
            result = await self._session.call_tool(name, args)
        except Exception as e:
            print(f"[tool] {name} failed: {e}")
            return {}
        if result.isError:
            return {"error": self._result_text(result)}
        return result.structuredContent or {}

    async def _send_message(self, message) -> Optional[types.GenerateContentResponse]:
        """Wraps chat.send_message with a short retry for transient Gemini API errors (503
        "high demand", 429 rate/quota limited). Returns None, after printing the error, if the
        call still fails."""
        for attempt in range(MAX_RETRIES):
            try:
                return await self.chat.send_message(message)
            except genai_errors.APIError as e:
                if e.code not in RETRYABLE_STATUS_CODES or attempt == MAX_RETRIES - 1:
                    print(f"[model] Gemini call failed ({e.code}): {e.message}")
                    return None
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
            except Exception as e:
                print(f"[model] Gemini call failed: {e}")
                return None

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
            answer = await agent.ask(user_input)
            print(f"\nAgent: {answer or NO_ANSWER_MESSAGE}")


if __name__ == "__main__":
    asyncio.run(_cli_chat())
