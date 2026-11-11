import { createContext, type ComponentChildren } from 'preact';
import { useContext, useReducer } from 'preact/hooks';
import {
  connectionReducer,
  initialConnectionState,
  type ConnectionAction,
  type ConnectionState,
} from './connection-reducer';
import { taskReducer, initialTaskState, type TaskAction, type TaskUiState } from './task-reducer';
import { micReducer, initialMicState, type MicAction, type MicState } from './mic-reducer';

interface AppStateValue {
  connection: ConnectionState;
  dispatchConnection: (action: ConnectionAction) => void;
  task: TaskUiState;
  dispatchTask: (action: TaskAction) => void;
  mic: MicState;
  dispatchMic: (action: MicAction) => void;
}

const AppStateContext = createContext<AppStateValue | null>(null);

/** One provider, three independent reducers -- each state machine
 * (connection, task lifecycle, mic gating) stays a small, separately
 * testable pure function; this is just where they're composed for the
 * component tree. */
export function AppStateProvider({ children }: { children: ComponentChildren }) {
  const [connection, dispatchConnection] = useReducer(connectionReducer, initialConnectionState);
  const [task, dispatchTask] = useReducer(taskReducer, initialTaskState);
  const [mic, dispatchMic] = useReducer(micReducer, initialMicState);

  const value: AppStateValue = { connection, dispatchConnection, task, dispatchTask, mic, dispatchMic };
  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>;
}

export function useAppState(): AppStateValue {
  const ctx = useContext(AppStateContext);
  if (!ctx) throw new Error('useAppState must be used within AppStateProvider');
  return ctx;
}
