type Props = {
  tag: string;
  name: string;
  empty?: boolean;
};

export default function FileCard({ tag, name, empty }: Props) {
  return (
    <div className={`file-card${empty ? " empty" : ""}`}>
      <div className="tag">{tag}</div>
      <div className="name">{empty ? "未选择制度文档" : name}</div>
    </div>
  );
}
