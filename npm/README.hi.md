<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.md">English</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/mcp-tool-shop-org/prism-verify/main/assets/prism-verify-logo.png" alt="prism-verify" width="500">
</p>

<p align="center">
  <a href="https://pypi.org/project/prism-verify/"><img src="https://img.shields.io/pypi/v/prism-verify" alt="PyPI"></a>
  <a href="https://www.npmjs.com/package/@mcptoolshop/prism-verify"><img src="https://img.shields.io/npm/v/@mcptoolshop/prism-verify" alt="npm"></a>
  <a href="https://github.com/mcp-tool-shop-org/prism-verify"><img src="https://img.shields.io/badge/source-GitHub-blue" alt="source"></a>
</p>

# @mcptoolshop/prism-verify

शून्य पूर्व-आवश्यकताओं के साथ [`prism`](https://github.com/mcp-tool-shop-org/prism-verify) का **npx** इंस्टॉलेशन।
सीएलआई — एक रनटाइम एलएलएम सत्यापनकर्ता (परिवार-विभिन्न, तर्क-मुक्त, बहु-लेंस, हस्ताक्षरित एड25519
प्राप्तियां)।

```bash
npx @mcptoolshop/prism-verify verify --artifact @myfile.py --intent "..." --caller-family openai
# or install it on your PATH
npm install -g @mcptoolshop/prism-verify
```

यह [`@mcptoolshop/npm-launcher`](https://github.com/mcp-tool-shop-org/npm-launcher) के ऊपर एक पतला रैपर है:
यह प्लेटफ़ॉर्म-विशिष्ट `prism` बाइनरी को
[prism-verify GitHub रिलीज़](https://github.com/mcp-tool-shop-org/prism-verify/releases) से डाउनलोड करता है,
**इसके SHA256 चेकसम को सत्यापित करता है**, इसे कैश करता है (`~/.cache/mcptoolshop/prism/<version>/`), और इसे चलाता है।
नेटवर्क एक्सेस केवल HTTPS के माध्यम से GitHub तक है; कोई टेलीमेट्री नहीं, कोई क्रेडेंशियल संग्रहीत नहीं।

**क्या आप पायथन पैकेज पसंद करेंगे?** `uv tool install prism-verify` / `pipx install prism-verify`
(PyPI, PEP 740 उत्पत्ति सत्यापन के साथ)। शून्य-पायथन `npx` उपयोग के लिए npm रैपर मौजूद है;
बंडल की गई बाइनरी सीएलआई + स्थानीय (ओलामा) सत्यापन + एचटीटीपी सेवा + उद्धरण
सत्यापन (एक वैकल्पिक स्व-होस्टेड ग्राउंडेडनेस सत्यापनकर्ता सहित) + `prism eval` अंशांकन
बेंचमार्क को कवर करती है। होस्टेड-प्रदाता सत्यापनकर्ता (एंथ्रोपिक /
ओपनएआई / गूगल) और पूर्ण अतिरिक्त PyPI इंस्टॉलेशन के साथ आते हैं।

पूर्ण दस्तावेज़, सुरक्षा मॉडल और स्रोत: <https://github.com/mcp-tool-shop-org/prism-verify>।

एमआईटी © mcp-tool-shop
