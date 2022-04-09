<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li><a href="#usage">Usage</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#contact">Contact</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
  </ol>
</details>

[![Python Version](https://img.shields.io/badge/python-3.10.x-brightgreen.svg)](https://python.org)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![issues](https://img.shields.io/github/issues/mathieeo/microcom)](https://github.com/mathieeo/microcom/issues)
[![issues](https://img.shields.io/github/languages/count/mathieeo/microcom)](https://github.com/mathieeo/microcom)
[![issues](https://img.shields.io/github/languages/code-size/mathieeo/microcom)](https://github.com/mathieeo/microcom)
[![issues](https://img.shields.io/github/followers/mathieeo?style=social)](https://github.com/mathieeo/microcom)


# [<img alt="" width="30x" src="https://static.wixstatic.com/media/b3d4ff_6d86c4d4b77245d8894a815b759ed7fd~mv2.png/v1/fill/w_132,h_119,al_c,usm_0.66_1.00_0.01,enc_auto/logo.png" />](https://integratedsw.tech) Integrated Software Technologies Inc.

[<img alt="alt_text" width="300x" src="https://static.wixstatic.com/media/b3d4ff_fd5635e886fa4ff1ab24e822f2fc4bbc~mv2.gif" />](https://integratedsw.tech)
<!-- ABOUT THE PROJECT -->
## About The Project

MicroCOM is a free software for accessing the serial port.
Please reed the license agreement for more details.

<p align="right">(<a href="#top">back to top</a>)</p>

# Supported Operating-Systems
* **Microsoft Windows v10 64-bit**
* **MacOS Monterey v12.2.1**
* **Ubuntu 20.04**
* **RedHat 8.5**

<p align="right">(<a href="#top">back to top</a>)</p>

### Built With

This section should list any major frameworks/libraries used to bootstrap your project. Leave any add-ons/plugins for the acknowledgements section. Here are a few examples.

* [Python](https://www.python.org)
* [prompt_toolkit](https://python-prompt-toolkit.readthedocs.io/en/master/)
* [pyperclip](https://pypi.org/project/pyperclip/)
* [argparse](https://docs.python.org/3/library/argparse.html)
* [pre-commit](https://pre-commit.com)
* [pylintpylint](https://pylint.org)
* [serial](https://pyserial.readthedocs.io/en/latest/)
<p align="right">(<a href="#top">back to top</a>)</p>

<!-- GETTING STARTED -->
## Getting Started

This is an example of how you may give instructions on setting up your project locally.
To get a local copy up and running follow these simple example steps.


### Installation

_Below is an example of how you can instruct your audience on installing and setting up your app. This template doesn't rely on any external dependencies or services._

1. Clone the repo
   ```sh
   git clone https://github.com/mathieeo/microcom.git
   ```
2. Install virtual environment
   ```sh
   pip install virtualenv
   ```
3. Run virtual
   ```sh
   virtualenv venv && source venv/bin/activate
   ```
4. Install requirements
   ```sh
   pip install -r requirements.txt
   ```

<p align="right">(<a href="#top">back to top</a>)</p>



<!-- USAGE EXAMPLES -->
## Usage

From the terminal (Console) cd to the project directory from there execute the following command:
   ```sh
   python3.10 microcom.py
   ```

###Application arguments:

|  Argument   | pram |       Description        |
|:-----------:|:----:|:------------------------:|
| --simulator |  -s  |  Run in simulator mode   |
|  --config   |  -c  | re-configure serial port |

###in-app Options:

|       Option       |    Key    |                       Description                        |
|:------------------:|:---------:|:--------------------------------------------------------:|
|        Quit        | Control+Q |                   Quit the application                   |
|     Clear Log      | Control+X |                  Clears the output log                   |
|     Pauses Log     | Control+P |                 Pause the output logging                 |
|   Export to File   | Control+S |             Export the output log to a file              |
| Start/Stop Capture | Control+W |   Start the capture mode. Save portion of output log.    |
| Copy to Clipboard  | Control+C |           Copy the entire log to the clipboard           |
| Highlight Pattern  | Control+S |          Search and find for a specific string           |
|   Find and Stop    | Control+G | Search and find for a specific string and stop if found. |
|    Show License    | Control+L |          Show the license for this application.          |
|        Help        | Control+H |                Used to show help string.                 |
|       Debug        | Shift+Tab |                    Used for debuting.                    |

<p align="right">(<a href="#top">back to top</a>)</p>



<!-- ROADMAP -->
## Roadmap

- [x] Add Changelog
- [x] Add back to top links
- [ ] Add Additional Templates w/ Examples
- [ ] Add "components" document to easily copy & paste sections of the readme


See the [open issues](https://github.com/mathieeo/microcom/issues) for a full list of proposed features (and known issues).

<p align="right">(<a href="#top">back to top</a>)</p>



<!-- CONTRIBUTING -->
## Contributing

Contributions are what make the open source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

If you have a suggestion that would make this better, please fork the repo and create a pull request. You can also simply open an issue with the tag "enhancement".
Don't forget to give the project a star! Thanks again!

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

<p align="right">(<a href="#top">back to top</a>)</p>



<!-- LICENSE -->
## License

Distributed under the GNU GPLv3 License. See `LICENSE` for more information.

<p align="right">(<a href="#top">back to top</a>)</p>


<!-- CONTACT -->
## Contact

Matthew - [eMail](mailto:matt@integratedsw.tech?subject=MicroCOM)

Project Link: [MicroCOM](https://github.com/mathieeo/microcom)

<p align="right">(<a href="#top">back to top</a>)</p>
