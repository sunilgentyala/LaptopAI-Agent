"""LangGraph-based agentic workflow for LaptopAI."""

from typing import Annotated, TypedDict
import operator

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from src.agent.tools import ALL_TOOLS
from src.security.audit import get_audit


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], operator.add]
    iterations: int


def build_graph(config: dict) -> StateGraph:
    llm_cfg = config.get("llm", {})
    llm = ChatOllama(
        model=llm_cfg.get("model", "qwen2.5-coder:7b"),
        base_url=llm_cfg.get("base_url", "http://localhost:11434"),
        temperature=llm_cfg.get("temperature", 0.1),
    ).bind_tools(ALL_TOOLS)

    tool_node = ToolNode(ALL_TOOLS)
    max_iterations = 10

    def call_llm(state: AgentState) -> AgentState:
        get_audit().log("AGENT", "LaptopAI", "llm_call", "",
                        f"iter={state['iterations']}")
        response = llm.invoke(state["messages"])
        return {
            "messages": [response],
            "iterations": state["iterations"] + 1,
        }

    def should_continue(state: AgentState) -> str:
        if state["iterations"] >= max_iterations:
            return END
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_llm)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    return graph.compile()


def run_agent(query: str, config: dict) -> str:
    graph = build_graph(config)
    initial_state = {
        "messages": [HumanMessage(content=query)],
        "iterations": 0,
    }
    get_audit().log("SESSION", "user", "query", query[:200], "started")
    final = graph.invoke(initial_state)
    last = final["messages"][-1]
    result = last.content if isinstance(last, AIMessage) else str(last)
    get_audit().log("SESSION", "LaptopAI", "response", "", result[:200])
    return result
