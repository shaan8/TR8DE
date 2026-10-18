import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import Negotiate from "./Negotiate.jsx";
import SupplierView from "./SupplierView.jsx";
import { Gate } from "./Login.jsx";
import "./index.css";

const view = new URLSearchParams(window.location.search).get("view");
const Page = view === "negotiate" ? Negotiate : view === "supplier" ? SupplierView : App;
// The supplier view has its own per-supplier token; everything else is the owner's and needs a sign-in.
createRoot(document.getElementById("root")).render(view === "supplier" ? <Page /> : <Gate><Page /></Gate>);
