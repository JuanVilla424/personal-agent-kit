# Vendored 3D engine

The brain page draws with [three.js](https://threejs.org/) r128. These files are that release as
its authors publish it, kept in the repository so the page loads on a machine without internet:
`index.html` asks no other server for code.

| File                | Source                                              | SHA-256                                                            |
| ------------------- | --------------------------------------------------- | ------------------------------------------------------------------ |
| `three.min.js`      | npm package `three@0.128.0`, `build/three.min.js`   | `9274bbcec8d96168626c732b5d31c775aa8cfb7eaa0599bec0c175908a2c1ce2` |
| `OrbitControls.js`  | npm package `three@0.128.0`, `examples/js/controls` | `02bb4ade710f3e607329e37a21f098bc3ac70eb6e33daf8a65e79f4db785e7b2` |
| `LICENSE-three.txt` | npm package `three@0.128.0`, `LICENSE` (MIT)        | `7dddf7c5b8fd10ee654db8857d75d104b5557889aa5a91fc4ca545ea7c07062f` |

Never edit them. To change the release, replace the three files and update this table;
`local/scripts/memory_index/tests/test_brain_ui.py` checks the hashes on every run.
