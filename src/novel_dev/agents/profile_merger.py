from typing import List
from pydantic import BaseModel

from novel_dev.agents.style_profiler import StyleProfile, StyleConfig


class Conflict(BaseModel):
    field: str
    old_value: str
    new_value: str
    resolution: str


class MergeResult(BaseModel):
    merged_profile: StyleProfile
    conflicts: List[Conflict]


class ProfileMerger:
    def merge(self, old: StyleProfile, new: StyleProfile) -> MergeResult:
        merged_config = old.style_config.model_copy(deep=True)
        new_config = new.style_config
        conflicts: List[Conflict] = []

        for field, new_value in new_config.model_dump().items():
            old_value = getattr(merged_config, field)
            if not old_value and new_value:
                setattr(merged_config, field, new_value)
            elif old_value and new_value and old_value != new_value:
                # Conflict on primitive string fields
                if isinstance(old_value, str) and isinstance(new_value, str):
                    conflicts.append(Conflict(
                        field=field,
                        old_value=old_value,
                        new_value=new_value,
                        resolution="Samples differ; manual review recommended",
                    ))
                    # Keep new value as default resolution
                    setattr(merged_config, field, new_value)
                else:
                    # For dicts/lists, prefer new if non-empty
                    setattr(merged_config, field, new_value)
            elif not old_value and not new_value:
                continue
            else:
                # old has value, new is empty -> keep old
                pass

        merged_guide = f"{old.style_guide}\n\n[Updated]\n{new.style_guide}"
        merged_profile = StyleProfile(style_guide=merged_guide, style_config=merged_config)
        return MergeResult(merged_profile=merged_profile, conflicts=conflicts)
