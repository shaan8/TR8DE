import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import Negotiate from "./Negotiate.jsx";
import SupplierView from "./SupplierView.jsx";
import "./index.css";

const view = new URLSearchParams(window.location.search).get("view");
const Page = view === "negotiate" ? Negotiate : view === "supplier" ? SupplierView : App;
createRoot(document.getElementById("root")).render(<Page />);
