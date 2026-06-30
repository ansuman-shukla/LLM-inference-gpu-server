"""Create an API key and print the raw key once."""

import argparse
import asyncio
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.core.config import get_settings
from backend.db.postgres import create_postgres_engine, create_sessionmaker
from backend.models.project import Project
from backend.models.user import User
from backend.repositories.api_key_repository import ApiKeyRepository
from backend.services.auth.api_key_service import ApiKeyService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a gpu-inference API key")
    parser.add_argument("--user-id", help="Existing user ID. Requires --project-id.")
    parser.add_argument("--project-id", help="Existing project ID. Requires --user-id.")
    parser.add_argument("--user-email", help="Find or create a user by email.")
    parser.add_argument("--user-name", help="Name to use when creating a user.")
    parser.add_argument("--project-name", help="Find or create a project for --user-email.")
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--allowed-model",
        action="append",
        dest="allowed_models",
        help="Allowed model ID. Repeat for multiple models. Omit to allow all models.",
    )
    parser.add_argument(
        "--expires-at",
        help="Optional ISO-8601 UTC timestamp, for example 2026-06-30T00:00:00+00:00.",
    )
    args = parser.parse_args()
    has_ids = bool(args.user_id and args.project_id)
    has_bootstrap = bool(args.user_email and args.project_name)
    if not has_ids and not has_bootstrap:
        parser.error("provide either --user-id/--project-id or --user-email/--project-name")
    if bool(args.user_id) != bool(args.project_id):
        parser.error("--user-id and --project-id must be provided together")
    return args


def parse_expires_at(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


async def main() -> None:
    args = parse_args()
    settings = get_settings()
    engine = create_postgres_engine(settings.database_url)
    sessionmaker = create_sessionmaker(engine)
    try:
        user_id, project_id = await resolve_user_project(sessionmaker, args)
        service = ApiKeyService(
            ApiKeyRepository,
            sessionmaker,
            key_prefix=settings.api_key_prefix,
        )
        created = await service.create_api_key(
            user_id=user_id,
            project_id=project_id,
            name=args.name,
            allowed_models=args.allowed_models,
            expires_at=parse_expires_at(args.expires_at),
        )
    finally:
        await engine.dispose()

    print(f"api_key_id={created.api_key_id}")
    print(f"key_prefix={created.key_prefix}")
    print(f"raw_key={created.raw_key}")


async def resolve_user_project(
    sessionmaker: async_sessionmaker, args: argparse.Namespace
) -> tuple[str, str]:
    if args.user_id and args.project_id:
        return args.user_id, args.project_id

    async with sessionmaker() as session:
        async with session.begin():
            user_result = await session.execute(select(User).where(User.email == args.user_email))
            user = user_result.scalar_one_or_none()
            if user is None:
                user = User(email=args.user_email, name=args.user_name)
                session.add(user)
                await session.flush()

            project_result = await session.execute(
                select(Project).where(
                    Project.user_id == user.id,
                    Project.name == args.project_name,
                )
            )
            project = project_result.scalar_one_or_none()
            if project is None:
                project = Project(user_id=user.id, name=args.project_name)
                session.add(project)
                await session.flush()

            return user.id, project.id


if __name__ == "__main__":
    asyncio.run(main())
