export interface CollapseToggleProps {
  direction: "left" | "right";
  collapsed: boolean;
  onToggle: () => void;
}

export default function CollapseToggle({
  direction,
  collapsed,
  onToggle,
}: CollapseToggleProps) {
  const sideClass = direction === "left" ? "left-0" : "right-0";

  return (
    <button
      type="button"
      onClick={onToggle}
      className={`absolute top-1/2 z-10 -translate-y-1/2 ${sideClass} flex h-8 w-5 items-center justify-center rounded-sm bg-gray-200 text-gray-500 opacity-0 transition-opacity hover:bg-gray-300 hover:text-gray-700 group-hover:opacity-100`}
      aria-label={collapsed ? `展开${direction === "left" ? "左侧" : "右侧"}面板` : `收起${direction === "left" ? "左侧" : "右侧"}面板`}
      title={collapsed ? "展开面板" : "收起面板"}
    >
      <svg
        className="h-3 w-3"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d={
            collapsed
              ? direction === "left"
                ? "M9 5l7 7-7 7"   // expand left: right arrow
                : "M15 5l-7 7 7 7" // expand right: left arrow
              : direction === "left"
                ? "M15 5l-7 7 7 7" // collapse left: left arrow
                : "M9 5l7 7-7 7"   // collapse right: right arrow
          }
        />
      </svg>
    </button>
  );
}
