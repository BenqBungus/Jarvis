import { useMemo } from 'preact/hooks';
import { AppStateProvider, useAppState } from './state/app-state';
import { createCompanionClient } from './companion-client/select-adapter';
import { summarizeConnection } from './state/connection-reducer';
import { isTaskInFlight } from './state/task-reducer';
import { useOnlineStatus } from './hooks/useOnlineStatus';
import { useTaskPolling } from './hooks/useTaskPolling';
import { useMicPermission } from './hooks/useMicPermission';
import { useConversationLog } from './hooks/useConversationLog';
import { ConnectionBanner } from './components/ConnectionBanner/ConnectionBanner';
import { MockModeBadge } from './components/MockModeBadge/MockModeBadge';
import { ConversationView } from './components/ConversationView/ConversationView';
import { TaskProgressPanel } from './components/TaskProgressPanel/TaskProgressPanel';
import { ComposerBar } from './components/ComposerBar/ComposerBar';
import { PushToTalkButton } from './components/PushToTalkButton/PushToTalkButton';
import { ErrorToast } from './components/ErrorToast/ErrorToast';
import styles from './app.module.css';

function AppShell() {
  // Created once per app lifetime, not per render -- both adapters hold no
  // per-render state of their own, but re-creating the client would restart
  // the mock adapter's in-memory task store for no reason.
  const client = useMemo(() => createCompanionClient(), []);
  const { connection, task } = useAppState();
  const taskInFlight = isTaskInFlight(task);

  useOnlineStatus(client, taskInFlight);
  const { submit, retry, cancel, dismiss } = useTaskPolling(client);
  const { mic, requestMicAccess } = useMicPermission();
  const entries = useConversationLog(task);

  const connectionSummary = summarizeConnection(connection);
  const submitErrorMessage = task.phase === 'submit_failed' ? task.message : null;

  return (
    <div class={styles.shell}>
      <MockModeBadge mode={client.mode} />
      <ConnectionBanner summary={connectionSummary} deviceName={connection.capabilities?.device_name} />
      <ConversationView entries={entries} />
      <TaskProgressPanel task={task} onCancel={cancel} onDismiss={dismiss} onRetry={retry} />
      <div class={styles.bottomBar}>
        <ComposerBar disabled={taskInFlight} onSubmit={submit} />
        <PushToTalkButton mic={mic} onRequestAccess={requestMicAccess} />
      </div>
      <ErrorToast message={submitErrorMessage} onDismiss={dismiss} />
    </div>
  );
}

export function App() {
  return (
    <AppStateProvider>
      <AppShell />
    </AppStateProvider>
  );
}
