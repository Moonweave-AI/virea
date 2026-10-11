"""Route work by user intent, without requiring a conversation for Motion Lab."""

from virea_contracts.performance import InteractionRequestV1


class RequestRouter:
    def __init__(self, *, motion_lab, character_studio, vrchat_studio):
        self.handlers = {
            "motion_lab": motion_lab,
            "character_studio": character_studio,
            "vrchat_studio": vrchat_studio,
        }

    async def submit(self, request: InteractionRequestV1):
        if request.workflow != "motion_lab" and not request.session_id:
            raise ValueError("interactive workflows require a session")
        return await self.handlers[request.workflow](request)
