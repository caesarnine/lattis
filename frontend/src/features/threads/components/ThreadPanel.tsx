import { ThreadSidebar, type ThreadSidebarProps } from "@/features/threads/components/ThreadSidebar";

type ThreadPanelProps = {
  isOpen: boolean;
  onClose: () => void;
  sidebarProps: ThreadSidebarProps;
};

export function ThreadPanel({ isOpen, onClose, sidebarProps }: ThreadPanelProps) {
  return (
    <>
      <div className="hidden md:block md:w-80">
        <ThreadSidebar {...sidebarProps} />
      </div>

      {isOpen ? (
        <div className="fixed inset-0 z-40 md:hidden">
          <div
            className="absolute inset-0 bg-ink-900/40 backdrop-blur-sm"
            onClick={onClose}
          />
          <div className="absolute inset-x-0 bottom-0 top-0">
            <ThreadSidebar {...sidebarProps} onClose={onClose} />
          </div>
        </div>
      ) : null}
    </>
  );
}
