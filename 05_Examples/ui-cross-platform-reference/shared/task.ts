export type Task = Readonly<{ id: string; title: string; done: boolean }>;

export type TaskState =
  | { kind: "loading" }
  | { kind: "empty" }
  | { kind: "success"; tasks: readonly Task[] }
  | { kind: "error"; message: string };

export interface TaskRepository {
  list(): Promise<readonly Task[]>;
}

export function validateTaskTitle(value: string): string | null {
  const title = value.trim();
  if (!title) return "Enter a task title.";
  if (title.length > 80) return "Keep the task title at 80 characters or fewer.";
  return null;
}

export function projectTasks(tasks: readonly Task[]): TaskState {
  return tasks.length === 0 ? { kind: "empty" } : { kind: "success", tasks };
}

export async function loadTasks(repository: TaskRepository): Promise<TaskState> {
  try {
    return projectTasks(await repository.list());
  } catch {
    return { kind: "error", message: "Tasks could not be loaded." };
  }
}
