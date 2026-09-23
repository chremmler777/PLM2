/**
 * In-memory BroadcastChannel for tests. Delivers synchronously to every other
 * open channel with the same name, never to the sender, like the real one.
 */
type Listener = (event: { data: unknown }) => void;

export class FakeBroadcastChannel {
  static open: FakeBroadcastChannel[] = [];

  static reset(): void {
    FakeBroadcastChannel.open = [];
  }

  readonly name: string;
  onmessage: Listener | null = null;

  constructor(name: string) {
    this.name = name;
    FakeBroadcastChannel.open.push(this);
  }

  postMessage(data: unknown): void {
    for (const channel of [...FakeBroadcastChannel.open]) {
      if (channel !== this && channel.name === this.name) channel.onmessage?.({ data });
    }
  }

  close(): void {
    FakeBroadcastChannel.open = FakeBroadcastChannel.open.filter((c) => c !== this);
  }
}
