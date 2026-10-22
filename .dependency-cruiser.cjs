/** TS 侧依赖边界，见 docs/ARCHITECTURE.md。Rust 侧边界由 Cargo.toml 的依赖声明保证。 */
module.exports = {
  forbidden: [
    { name: "packages-not-depend-on-apps", severity: "error",
      from: { path: "^packages/" }, to: { path: "^apps/" } },
    { name: "apps-not-depend-on-each-other", severity: "error",
      from: { path: "^apps/([^/]+)/" }, to: { path: "^apps/", pathNot: "^apps/$1/" } },
    { name: "no-circular", severity: "error", from: {}, to: { circular: true } }
  ],
  options: { doNotFollow: { path: "node_modules" }, tsConfig: { fileName: "tsconfig.json" } }
};
