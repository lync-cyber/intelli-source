"""Built-in digest templates — imported for their registration side effect."""

from intellisource.distributor.templates.builtin.daily_brief import DailyBriefTemplate
from intellisource.distributor.templates.builtin.json_feed import JsonFeedTemplate
from intellisource.distributor.templates.builtin.push_card import PushCardTemplate
from intellisource.distributor.templates.builtin.topic_deepdive import (
    TopicDeepDiveTemplate,
)
from intellisource.distributor.templates.builtin.weekly_roundup import (
    WeeklyRoundupTemplate,
)
from intellisource.distributor.templates.registry import register_template

for _template_cls in (
    DailyBriefTemplate,
    WeeklyRoundupTemplate,
    TopicDeepDiveTemplate,
    PushCardTemplate,
    JsonFeedTemplate,
):
    register_template(_template_cls())
