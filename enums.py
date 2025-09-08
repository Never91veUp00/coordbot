from enum import Enum

class TaskStatus(str, Enum):
    """Статусы задач"""
    PENDING = "pending"     # назначена, ждет принятия
    ACCEPTED = "accepted"   # отряд принял
    FINISHED = "finished"   # закрыта отчётом
    ARCHIVED = "archived"   # старая версия
