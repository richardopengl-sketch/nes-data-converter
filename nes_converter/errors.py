class Rejection(ValueError):
    """A known unsupported source case, not an implementation failure."""

    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")


class MappingSkip(ValueError):
    def __init__(self, reason: str, detail: str):
        self.reason = reason
        super().__init__(detail)


class VerificationError(RuntimeError):
    def __init__(self, stage: str, private_detail: str):
        self.stage = stage
        self.private_detail = private_detail
        super().__init__(f"{stage} validation failed; details belong in private run output")
