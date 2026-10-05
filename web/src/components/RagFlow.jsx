import { ScrollText } from "lucide-react";
import { GameIcon } from "../ui/GameIcon";

const labels = {
  pending: "等待",
  running: "进行中",
  done: "完成",
  skip: "跳过",
  error: "失败",
};

export function RagFlow({ steps = [], active = false }) {
  return (
    <section className="px-3 pt-3">
      <div className="mb-2 flex items-center gap-2 text-grass-deep">
        <ScrollText size={18} />
        <strong>任务卷轴</strong>
        <span className="text-sm">{active ? "正在按步骤检索并生成" : "发送问题后，这里会逐步点亮"}</span>
      </div>
      <ol className="flex gap-2 overflow-x-auto pb-1">
        {steps.map((step) => (
          <li key={step.id} className="ui-frame min-w-36 shrink-0 px-3 py-2">
            <div className="relative z-10">
              <GameIcon id="icon-mode-search" icon={ScrollText} size={18} />
              <strong className="mt-1 block text-sm">{step.label}</strong>
              <em className="text-xs not-italic text-wood">{labels[step.status] || "等待"}</em>
              {step.detail ? <p className="text-xs leading-snug">{step.detail}</p> : null}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
