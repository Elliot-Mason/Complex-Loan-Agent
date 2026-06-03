"""
Vulnerable Loan Application AI Agent (AWS Bedrock Edition)
==========================================================
FOR TRAINING / PENETRATION TESTING LAB USE ONLY.
This agent contains intentional security vulnerabilities.
Do NOT deploy in any production environment.
"""

import argparse
import json
import logging
import os
import uuid
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import boto3
from botocore.config import Config
import requests
import database as db

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_FILE = LOG_DIR / "complex_loan_agent.log"

# ... (logger config)

class LoanAgent:
    def __init__(self, current_user_id: str, session_id: Optional[str] = None, model: str = "au.anthropic.claude-sonnet-4-5-20250929-v1:0"):
        user = db.get_user(current_user_id)
        if not user:
            raise ValueError(f"User '{current_user_id}' not found.")

        self.current_user = user
        self.session_id = session_id or f"sess_{uuid.uuid4().hex[:8]}"
        self.model = model
        print(f"--- DEBUG: INITIALIZING AGENT WITH MODEL: {self.model} | SESSION: {self.session_id} ---")
        
        # Load history from database
        self.messages = db.get_chat_history(self.session_id)

        # Increase timeout for high-latency Bedrock responses during red-teaming
        bedrock_config = Config(
            connect_timeout=10,
            read_timeout=300,
            retries={"max_attempts": 0}
        )
        self.bedrock = boto3.client("bedrock-runtime", region_name="ap-southeast-2", config=bedrock_config)

        self.tools = BEDROCK_TOOLS
        if self.current_user["role"] == "Applier":
            self.tools = [t for t in BEDROCK_TOOLS if t["toolSpec"]["name"] != "update_user_profile"]

        self.system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            user_id=self.current_user["user_id"],
            username=self.current_user["username"],
            role=self.current_user["role"],
        )

    # ... (other methods)

    def chat(self, user_text: str) -> str:
        if self._contains_competitor(user_text):
            denial = "Your request has been denied. You mentioned a competitor, which violates our policy."
            log_event("chat.denied", user_id=self.current_user["user_id"], message=user_text)
            return denial

        log_event("chat.request", user_id=self.current_user["user_id"], message=user_text)
        
        # SAVE User Message
        user_msg_content = [{"text": user_text}]
        self.messages.append({"role": "user", "content": user_msg_content})
        self._save_message("user", user_msg_content)

        max_rounds = 10
        for i in range(max_rounds):
            start_time = time.perf_counter()
            try:
                response = self.bedrock.converse(
                    modelId=self.model,
                    messages=self.messages,
                    system=[{"text": self.system_prompt}],
                    toolConfig={"tools": self.tools}
                )
            except Exception as e:
                LOGGER.error(f"Bedrock API call failed: {e}")
                return f"Error: Bedrock timeout or failure. {e}"

            duration = round(time.perf_counter() - start_time, 2)
            LOGGER.info(f"Bedrock turn {i+1} completed in {duration}s")

            msg = response["output"]["message"]
            self.messages.append(msg)
            
            # SAVE Assistant Message (might contain tool calls)
            self._save_message("assistant", msg["content"])

            # Check if there are tool use requests
            tool_requests = [c["toolUse"] for c in msg["content"] if "toolUse" in c]
            if not tool_requests:
                final_text = "".join(c["text"] for c in msg["content"] if "text" in c)
                log_event("chat.response", user_id=self.current_user["user_id"], response=final_text)
                return final_text

            # Execute tools and build tool result message
            tool_results = []
            for tr in tool_requests:
                res = self._execute_tool(tr["name"], tr["input"], tool_call_id=tr["toolUseId"])
                tool_results.append({
                    "toolResult": {
                        "toolUseId": tr["toolUseId"],
                        "content": [{"json": res}]
                    }
                })
            
            # SAVE Tool Results as a user role
            self.messages.append({"role": "user", "content": tool_results})
            self._save_message("user", tool_results)

        return "Max conversation rounds reached."
