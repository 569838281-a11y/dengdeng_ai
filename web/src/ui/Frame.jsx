export function Frame({ variant = "dialog", className = "", children }) {
  return (
    <div className={`ui-frame ui-frame--${variant} ${className}`}>
      <i className="ui-corner ui-corner-tl" />
      <i className="ui-corner ui-corner-tr" />
      <i className="ui-corner ui-corner-bl" />
      <i className="ui-corner ui-corner-br" />
      <div className="relative z-10">{children}</div>
    </div>
  );
}
