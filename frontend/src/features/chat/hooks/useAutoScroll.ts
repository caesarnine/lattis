import React from "react";

type UseAutoScrollOptions = {
  offset?: number;
};

export function useAutoScroll(itemCount: number, options: UseAutoScrollOptions = {}) {
  const { offset = 100 } = options;
  const scrollRef = React.useRef<HTMLDivElement | null>(null);
  const [showScrollButton, setShowScrollButton] = React.useState(false);

  const scrollToBottom = React.useCallback(() => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth"
    });
  }, []);

  const handleScroll = React.useCallback(
    (event: React.UIEvent<HTMLDivElement>) => {
      const target = event.currentTarget;
      const isAtBottom =
        target.scrollHeight - target.scrollTop <= target.clientHeight + offset;
      setShowScrollButton(!isAtBottom);
    },
    [offset]
  );

  React.useEffect(() => {
    if (!showScrollButton) {
      scrollToBottom();
    }
  }, [itemCount, scrollToBottom, showScrollButton]);

  return {
    scrollRef,
    showScrollButton,
    scrollToBottom,
    handleScroll
  };
}
