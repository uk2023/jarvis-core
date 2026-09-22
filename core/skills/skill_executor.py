class SkillExecutor:
    def __init__(self, registry):
        self.registry = registry

    def execute(self, name, *args, **kwargs):
        skill = self.registry.get(name)

        if not skill:
            raise KeyError(f"Unknown skill: {name}")

        return skill(*args, **kwargs)
