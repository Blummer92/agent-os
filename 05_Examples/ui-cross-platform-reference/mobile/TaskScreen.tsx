import { useState } from "react";
import { Pressable, SafeAreaView, StyleSheet, Text, TextInput, View, useWindowDimensions } from "react-native";
import { TaskState, validateTaskTitle } from "../shared/task";

export type Capability = { requestPhotoAccess(): Promise<"granted" | "denied" | "unavailable"> };

export function TaskScreen({ state, capability }: { state: TaskState; capability: Capability }) {
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const [screen, setScreen] = useState<"tasks" | "details">("tasks");
  const { width } = useWindowDimensions();
  const tablet = width >= 768;

  async function checkPhotoAccess() {
    const result = await capability.requestPhotoAccess();
    setMessage(result === "granted" ? "Photo access available." : result === "denied" ? "Photo access denied." : "Photo capability unavailable.");
  }

  const validation = title ? validateTaskTitle(title) : null;

  return <SafeAreaView style={styles.safe}>
    <View style={[styles.container, tablet && styles.tablet]} accessibilityLabel="Task reference screen">
      <Text accessibilityRole="header" style={styles.heading}>{screen === "tasks" ? "Tasks" : "Task details"}</Text>
      {screen === "tasks" ? <>
        {state.kind === "loading" && <Text accessibilityLiveRegion="polite">Loading tasks…</Text>}
        {state.kind === "empty" && <Text>No tasks yet.</Text>}
        {state.kind === "error" && <Text accessibilityRole="alert">{state.message}</Text>}
        {state.kind === "success" && state.tasks.map(task => <Text key={task.id}>{task.title}</Text>)}
        <TextInput accessibilityLabel="New task" value={title} onChangeText={setTitle} style={styles.input} />
        {validation && <Text accessibilityRole="alert">{validation}</Text>}
        <Pressable accessibilityRole="button" accessibilityLabel="Open task details" style={styles.target} onPress={() => setScreen("details")}><Text>Open details</Text></Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="Check photo permission" style={styles.target} onPress={checkPhotoAccess}><Text>Check photo access</Text></Pressable>
        {!!message && <Text accessibilityLiveRegion="polite">{message}</Text>}
      </> : <Pressable accessibilityRole="button" accessibilityLabel="Back to tasks" style={styles.target} onPress={() => setScreen("tasks")}><Text>Back</Text></Pressable>}
    </View>
  </SafeAreaView>;
}

const styles = StyleSheet.create({ safe: { flex: 1 }, container: { flex: 1, gap: 12, padding: 16 }, tablet: { alignSelf: "center", maxWidth: 720, width: "100%" }, heading: { fontSize: 24, fontWeight: "600" }, input: { borderWidth: 1, minHeight: 44, padding: 10 }, target: { alignItems: "center", justifyContent: "center", minHeight: 44, paddingHorizontal: 12 } });
