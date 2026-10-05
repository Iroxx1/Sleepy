import { Link } from "react-router-dom";
import { Empty } from "../components/ui";

export default function NotFound() {
  return (
    <Empty>
      Seite nicht gefunden. <Link to="/">Zum Dashboard</Link>
    </Empty>
  );
}
