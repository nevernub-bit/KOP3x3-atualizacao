import React from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import "./App.css";
import { AuthProvider } from "./auth";
import { Toaster } from "sonner";
import { Layout } from "./components/Layout";
import Home from "./pages/Home";
import Register from "./pages/Register";
import Login from "./pages/Login";
import Admin from "./pages/Admin";
import Players from "./pages/Players";
import Teams from "./pages/Teams";
import TeamSelect from "./pages/TeamSelect";
import Matches from "./pages/Matches";
import MatchDetail from "./pages/MatchDetail";
import Standings from "./pages/Standings";
import Playoffs from "./pages/Playoffs";
import Stats from "./pages/Stats";
import Champion from "./pages/Champion";
import Live from "./pages/Live";
import Versus from "./pages/Versus";
import Rules from "./pages/Rules";

const withLayout = (C, opts = {}) => (
  <Layout {...opts}><C /></Layout>
);

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Toaster theme="dark" position="top-center" />
        <Routes>
          <Route path="/" element={withLayout(Home)} />
          <Route path="/register" element={withLayout(Register, { hideNav: true })} />
          <Route path="/login" element={withLayout(Login)} />
          <Route path="/admin" element={withLayout(Admin)} />
          <Route path="/players" element={withLayout(Players)} />
          <Route path="/teams" element={withLayout(Teams)} />
          <Route path="/team-select" element={withLayout(TeamSelect)} />
          <Route path="/matches" element={withLayout(Matches)} />
          <Route path="/matches/:mid" element={withLayout(MatchDetail)} />
          <Route path="/versus/:mid" element={withLayout(Versus, { hideNav: true })} />
          <Route path="/standings" element={withLayout(Standings)} />
          <Route path="/playoffs" element={withLayout(Playoffs)} />
          <Route path="/stats" element={withLayout(Stats)} />
          <Route path="/rules" element={withLayout(Rules)} />
          <Route path="/champion" element={withLayout(Champion)} />
          <Route path="/live" element={withLayout(Live, { hideNav: true })} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
