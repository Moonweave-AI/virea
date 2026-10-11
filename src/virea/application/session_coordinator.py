"""Turn epochs, body ownership and evidence shared by all session adapters."""

from uuid import uuid4

from virea_contracts.performance import ExecutionReceiptV1, SessionSnapshotV1


class SessionCoordinator:
    def __init__(self, session_id):
        self.session_id = session_id
        self.epoch = 0
        self.revision = 0
        self.turn_id = None
        self.state = "accepted"
        self.target_id = f"browser:{session_id}"
        self.target_kind = "browser"
        self.body_owner = None
        self.receipt = None

    def bind(self, target_id, target_kind):
        if self.body_owner is not None:
            raise ValueError("release the active body channel before changing targets")
        if target_kind not in {"browser", "vrchat"}:
            raise ValueError("unknown embodiment target")
        self.target_id, self.target_kind = target_id, target_kind

    def begin(self):
        self.turn_id = uuid4().hex
        self.state = "planning"
        self.receipt = None

    def advance(self):
        self.epoch += 1
        self.state = "cancelled"
        self.body_owner = None

    def require_current(self, epoch):
        if epoch != self.epoch:
            raise ValueError("performance belongs to a superseded turn")

    def preparing(self, epoch):
        self.require_current(epoch)
        self.state = "preparing"

    def ready(self, epoch):
        self.require_current(epoch)
        self.state = "ready"

    def claim_body(self, epoch, owner):
        self.require_current(epoch)
        if self.body_owner not in {None, owner}:
            raise ValueError("another execution owns the body channel")
        self.body_owner = owner
        self.state = "playing"

    def feedback(self, receipt: ExecutionReceiptV1):
        self.require_current(receipt.epoch)
        if receipt.session_id != self.session_id or receipt.target_id != self.target_id:
            raise ValueError("receipt identity differs from the active target")
        if self.body_owner != receipt.command_id:
            raise ValueError("receipt does not belong to the body owner")
        self.receipt = receipt
        self.state = {
            "completed": "completed",
            "failed": "failed",
            "interrupted": "holding",
            "accepted": "playing",
        }[receipt.status]
        if receipt.status != "accepted":
            self.body_owner = None

    def snapshot(self):
        return SessionSnapshotV1(
            session_id=self.session_id,
            turn_id=self.turn_id,
            epoch=self.epoch,
            revision=self.revision,
            state=self.state,
            target_id=self.target_id,
            body_owner=self.body_owner,
            receipt=self.receipt,
        ).model_dump(mode="json")
