"""Operator CLI: `python -m app.cli <command>`.

create-user  — create a user with a personal workspace and print a bearer token.
issue-token  — mint another token for an existing user.
openapi      — print the OpenAPI document (no database or storage needed).
export-training-dataset — write a private consent-filtered candidate dataset as JSONL.
promote-prompt-examples — select reviewed successful pairs for the live planner.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import sqlalchemy as sa

from app.auth import issue_token
from app.config import load_settings
from app.db import make_engine, make_session_factory, session_scope
from app.models.core import User, Workspace, WorkspaceKind, WorkspaceMember, WorkspaceRole


def create_user(email: str, display_name: str | None, workspace_name: str | None) -> int:
    settings = load_settings()
    factory = make_session_factory(make_engine(settings))
    with session_scope(factory) as db:
        if db.scalar(sa.select(User).where(User.email == email)) is not None:
            print(f"user {email} already exists", file=sys.stderr)
            return 1
        user = User(email=email, display_name=display_name)
        workspace = Workspace(
            name=workspace_name or f"{display_name or email}'s workspace",
            kind=WorkspaceKind.personal,
            owner=user,
        )
        membership = WorkspaceMember(workspace=workspace, user=user, role=WorkspaceRole.owner)
        db.add_all([user, workspace, membership])
        db.flush()
        token, _ = issue_token(db, user.id, label="cli")
        print(f"user_id={user.id}")
        print(f"workspace_id={workspace.id}")
        print(f"token={token}")
    return 0


def issue(email: str, label: str) -> int:
    settings = load_settings()
    factory = make_session_factory(make_engine(settings))
    with session_scope(factory) as db:
        user = db.scalar(sa.select(User).where(User.email == email))
        if user is None:
            print(f"no user {email}", file=sys.stderr)
            return 1
        token, _ = issue_token(db, user.id, label=label)
        print(f"token={token}")
    return 0


def openapi() -> int:
    """Emit the API schema; storage is stubbed so this works without any infrastructure."""
    import json

    from app.main import create_app
    from app.storage import ObjectStorage

    class _NoStorage:
        pass

    settings = load_settings()
    storage: ObjectStorage = _NoStorage()  # type: ignore[assignment]
    app = create_app(settings, storage=storage)
    print(json.dumps(app.openapi(), indent=2, ensure_ascii=False))
    return 0


def export_training_dataset(output: str) -> int:
    """Export to a restricted file without ever printing sample contents or the HMAC secret."""
    from app.services.training_dataset import export_candidate_dataset

    raw_secret = os.environ.get("TRAINING_DATASET_HASH_SECRET")
    if raw_secret is None or len(raw_secret.encode()) < 32:
        print(
            "TRAINING_DATASET_HASH_SECRET must be set to at least 32 bytes",
            file=sys.stderr,
        )
        return 2
    settings = load_settings()
    factory = make_session_factory(make_engine(settings))
    with session_scope(factory) as db:
        summary = export_candidate_dataset(db, destination=Path(output), secret=raw_secret.encode())
    print(
        f"wrote {summary.total_samples} candidate samples "
        f"({summary.ai_request_samples} AI, {summary.reconstruction_samples} reconstruction) "
        f"to {summary.destination}"
    )
    print("privacy review is required before training")
    return 0


def promote_examples(input_path: str, output: str, privacy_review: str, limit: int) -> int:
    """Build a deployable bundle; never print its prompts or plans."""
    from app.ai.prompt_examples import promote_prompt_examples

    try:
        summary = promote_prompt_examples(
            Path(input_path),
            destination=Path(output),
            review_reference=privacy_review,
            limit=limit,
        )
    except (OSError, ValueError) as exc:
        print(f"prompt example promotion failed: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {summary.examples} reviewed prompt examples to {summary.destination}")
    print(f"set AI_PROMPT_EXAMPLES_SHA256={summary.sha256} to deploy this exact bundle")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    cu = sub.add_parser("create-user")
    cu.add_argument("--email", required=True)
    cu.add_argument("--name")
    cu.add_argument("--workspace")
    it = sub.add_parser("issue-token")
    it.add_argument("--email", required=True)
    it.add_argument("--label", default="cli")
    sub.add_parser("openapi")
    dataset = sub.add_parser("export-training-dataset")
    dataset.add_argument("--output", required=True)
    examples = sub.add_parser("promote-prompt-examples")
    examples.add_argument("--input", required=True)
    examples.add_argument("--output", required=True)
    examples.add_argument("--privacy-review", required=True)
    examples.add_argument("--limit", type=int, default=8)
    args = parser.parse_args(argv)
    if args.command == "create-user":
        return create_user(args.email, args.name, args.workspace)
    if args.command == "openapi":
        return openapi()
    if args.command == "export-training-dataset":
        return export_training_dataset(args.output)
    if args.command == "promote-prompt-examples":
        return promote_examples(args.input, args.output, args.privacy_review, args.limit)
    return issue(args.email, args.label)


if __name__ == "__main__":
    sys.exit(main())
