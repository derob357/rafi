---
name: tasks
description: Create, list, update, complete, and delete tasks.
tools:
  - create_task
  - list_tasks
  - update_task
  - delete_task
  - complete_task
requires:
  env: []
---

# Tasks Skill

Use these tools to manage the user's task list stored in Supabase.

- `create_task`: Create a task with title, optional description and due date.
- `list_tasks`: List tasks, optionally filtered by status (pending/in_progress/completed).
- `update_task`: Update task fields by task_id.
- `complete_task`: Mark a task as completed.
- `delete_task`: Delete a task.
